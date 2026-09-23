# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Integration tests: ``scripts/install.sh`` must hand pip the right ``--index-url``.

``scripts/install.sh`` used to hardcode the NVIDIA cu128 wheel index and use it
on every host where ``nvidia-smi`` succeeded — blind to CPU architecture, the
driver's CUDA version and the GPU's compute capability.  On aarch64 that index
serves SBSA wheels built for sm_90/sm_100: they import cleanly and then die at
the FIRST KERNEL LAUNCH with "no kernel image is available for execution on
the device" — the worst failure mode, because install and configuration both
appeared to succeed.  The installer now resolves the wheel index from the host
(``kaine/wheel_index.py``) and this module is the evidence that

  (a) the resolved index actually reaches pip as ``--index-url``,
  (b) an explicit operator ``--index-url`` override wins where it must win,
  (c) the override is ignored — with a notice naming the flavor — where it
      must be ignored, and
  (d) the non-CUDA flavors (``--cpu``/``--rocm``/``--xpu``/``--mps``) were not
      disturbed by the change.

Technique: for every case a temporary directory of executable shim scripts is
put FIRST on ``PATH`` and ``bash scripts/install.sh <flags>`` is executed with
the repo root (derived from ``__file__``) as working directory.  The ``pip``
shim appends its full argv to a log file and exits 0, so every install attempt
is absorbed: nothing is installed; the installer is pointed at a skeleton venv
under ``tmp_path`` and the network is never touched.  ``nvidia-smi``/
``rocm-smi``/``xpu-smi``/``sycl-ls`` shims steer accelerator detection, and the
installer's detection semantics dictate how "absence" is simulated: NVIDIA is
accepted only where ``nvidia-smi`` exists AND ``nvidia-smi -L`` succeeds, while
ROCm (``rocm-smi`` or ``/opt/rocm``) and Intel XPU (``xpu-smi`` or ``sycl-ls``)
are detected by PRESENCE alone — ``command -v`` succeeds whenever the file
exists on PATH, whatever its exit code, so even a failing shim counts as
"present".  A broken nvidia-smi is therefore simulated with a present-but-failing
shim (which must exist, to shadow a real binary on GPU-equipped test hosts),
while absence of a presence-detected tool is simulated by omitting the shim
entirely; the module skips itself on hosts that carry the real ROCm/XPU
tooling, because no shim can hide a real binary.  The real interpreter runs the
wheel-index resolver: the ``python3``/``python`` shims delegate everything to
the real interpreter except ``-m venv`` (a skeleton virtualenv is fabricated —
no ensurepip, no network, no real venv anywhere) and ``-m pip`` (routed to the
pip shim, so it absorbs every install attempt).

Exit status: ``install.sh`` closes with a verification step that imports
torch.  Under the absorbing pip shim nothing is installed, so that
verification necessarily fails and ``install.sh`` legitimately exits non-zero
— exactly the behaviour expected of a real installer whose install did
nothing.  These tests therefore assert on WHICH INDEX REACHED PIP (the
recorded pip argv) and on the stderr notices, and deliberately never require
a zero exit status.

Every case is steered exclusively by flags and shims, so no assertion depends
on the architecture of the machine running the tests: the suite passes
unchanged on x86_64 CI runners and on the aarch64 Jetson.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def _host_has_presence_detected_accelerator() -> bool:
    """True where real ROCm/XPU tooling would defeat the omission trick.

    Absence of a presence-detected tool (``rocm-smi``, ``xpu-smi``,
    ``sycl-ls``, ``/opt/rocm``) is simulated by NOT writing its shim, so the
    simulation is faithful only where the real tool is absent: install.sh's
    ``command -v`` probe finds a real binary no matter what the tests do.
    ``nvidia-smi`` is deliberately not considered here — every case shadows
    it with a shim, because NVIDIA detection requires presence AND a working
    ``nvidia-smi -L``.
    """
    return (
        shutil.which("rocm-smi") is not None
        or shutil.which("xpu-smi") is not None
        or shutil.which("sycl-ls") is not None
        or Path("/opt/rocm").is_dir()
    )


pytestmark = [
    pytest.mark.skipif(
        os.name != "posix" or shutil.which("bash") is None,
        reason="bash/POSIX shell unavailable; scripts/install.sh cannot be exercised",
    ),
    pytest.mark.skipif(
        _host_has_presence_detected_accelerator(),
        reason=(
            "host carries real ROCm/XPU tooling; presence-only detection cannot "
            "be simulated as absent by omitting shims"
        ),
    ),
]

REPO_ROOT = Path(__file__).resolve().parents[1]

CPU_INDEX = "https://download.pytorch.org/whl/cpu"
ROCM_INDEX = "https://download.pytorch.org/whl/rocm6.2"
XPU_INDEX = "https://download.pytorch.org/whl/xpu"
OVERRIDE_INDEX = "https://example.invalid/custom"

RUN_TIMEOUT_SECONDS = 120


# ---------------------------------------------------------------------------
# Shim templates.  "@TOKENS@" are substituted per case; every shim is written
# into tmp_path, never into the repository.
# ---------------------------------------------------------------------------

_PIP_SHIM = r"""#!/bin/sh
# Test shim: append the full argv to the log, then absorb the invocation.
printf '%s\n' "$*" >> '@LOG@'
case "$1" in
  show)
    # Report "not installed" so the installer always reaches `pip install`.
    exit 1
    ;;
  --version|-V)
    printf 'pip 24.0 from @SHIM_DIR@/pip (python 3.11)\n'
    exit 0
    ;;
  *)
    exit 0
    ;;
esac
"""

_NVIDIA_SMI_OK_SHIM = r"""#!/bin/sh
# Test shim: a successful nvidia-smi with a steerable "CUDA Version" header,
# answering -L and --query-gpu=... --format=csv[,noheader].
for arg in "$@"; do
  if [ "$arg" = "-L" ]; then
    printf 'GPU 0: NVIDIA Test Device (UUID: GPU-11111111-2222-3333-4444-555555555555)\n'
    exit 0
  fi
done
case "$*" in
  *compute_cap*)
    case "$*" in
      *noheader*) printf '8.9\n' ;;
      *) printf 'compute_cap\n8.9\n' ;;
    esac
    exit 0
    ;;
  *--query-gpu=*)
    case "$*" in
      *noheader*) printf 'NVIDIA Test Device\n' ;;
      *) printf 'name\nNVIDIA Test Device\n' ;;
    esac
    exit 0
    ;;
esac
printf 'NVIDIA-SMI 550.54.15       Driver Version: 550.54.15       CUDA Version: @CUDA@\n'
printf '\n'
exit 0
"""

_NVIDIA_SMI_FAIL_SHIM = r"""#!/bin/sh
# Test shim: nvidia-smi PRESENT but failing.  NVIDIA detection requires both
# presence and a working `nvidia-smi -L`, so for install.sh this is
# indistinguishable from "no NVIDIA host" — and, unlike omission, the shim
# also shadows a real nvidia-smi on GPU-equipped test hosts.
printf 'NVIDIA-SMI has failed because it cannot communicate with the NVIDIA driver.\n' >&2
exit 1
"""

_ROCM_SMI_OK_SHIM = r"""#!/bin/sh
# Test shim: a successful rocm-smi.
printf '======================= ROCm System Management Interface =======================\n'
printf 'GPU[0] : Name: AMD Instinct MI210\n'
printf 'GPU[0] : Unique ID: 0\n'
printf '================================================================================\n'
exit 0
"""

_SYCL_LS_OK_SHIM = r"""#!/bin/sh
# Test shim: sycl-ls reporting one Level Zero GPU.
printf 'level_zero:gpu(0) Intel(R) Arc(TM) A770 Graphics [0x56a0]\n'
printf 'opencl:gpu(0) Intel(R) Arc(TM) A770 Graphics [0x56a0]\n'
exit 0
"""

_XPU_SMI_OK_SHIM = r"""#!/bin/sh
# Test shim: xpu-smi succeeds quietly.
exit 0
"""

_PYTHON_SHIM = r"""#!/bin/sh
# Transparent python shim: delegate to the real interpreter so that it (and
# only it) runs the wheel-index resolver.  Two exceptions keep the test
# hermetic: `-m venv` fabricates a skeleton virtualenv (no ensurepip, no
# network, no real venv anywhere) and `-m pip` is routed to the pip shim.
REAL='@REAL_PYTHON3@'
SHIM_DIR='@SHIM_DIR@'
state=0
is_venv=0
target=''
for arg in "$@"; do
  case "$state" in
    0)
      if [ "$arg" = '-m' ]; then state=1; fi
      ;;
    1)
      if [ "$arg" = 'venv' ]; then is_venv=1; state=2; else state=0; fi
      ;;
    2)
      case "$arg" in
        -*) : ;;
        *) if [ -z "$target" ]; then target="$arg"; fi ;;
      esac
      ;;
  esac
done
if [ "$is_venv" = '1' ] && [ -n "$target" ]; then
  mkdir -p "$target/bin"
  {
    printf 'home = %s\n' "$(dirname "$REAL")"
    printf 'include-system-site-packages = true\n'
    printf 'version = 3.11\n'
  } > "$target/pyvenv.cfg"
  {
    printf '#!/bin/sh\n'
    printf 'if [ "$1" = "-m" ] && [ "$2" = "pip" ]; then shift 2; exec "%s/pip" "$@"; fi\n' "$SHIM_DIR"
    printf 'exec "%s" "$@"\n' "$REAL"
  } > "$target/bin/python"
  chmod 0755 "$target/bin/python"
  cp "$SHIM_DIR/pip" "$target/bin/pip"
  cp "$SHIM_DIR/pip" "$target/bin/pip3"
  chmod 0755 "$target/bin/pip" "$target/bin/pip3"
  printf '# no-op activate (test shim)\n' > "$target/bin/activate"
  exit 0
fi
if [ "$#" -ge 2 ] && [ "$1" = '-m' ] && [ "$2" = 'pip' ]; then
  shift 2
  exec "$SHIM_DIR/pip" "$@"
fi
exec "$REAL" "$@"
"""


def _write_shim(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _index_urls(pip_log: str) -> list[str]:
    """Every ``--index-url`` value pip received, in recorded order."""
    urls: list[str] = []
    for line in pip_log.splitlines():
        tokens = line.split()
        for position, token in enumerate(tokens):
            if token in ("--index-url", "-i") and position + 1 < len(tokens):
                urls.append(tokens[position + 1])
            elif token.startswith("--index-url="):
                urls.append(token.split("=", 1)[1])
    return urls


def _context(proc: subprocess.CompletedProcess, pip_log: str) -> str:
    return (
        f"\ninstall.sh exit code: {proc.returncode}"
        f"\n--- stdout ---\n{proc.stdout}"
        f"\n--- stderr ---\n{proc.stderr}"
        f"\n--- pip argv log ---\n{pip_log}"
    )


def _venv_snapshot(venv_dir: Path) -> list[tuple[str, int]]:
    """Return a sorted snapshot of a venv directory for change detection.

    Records (relative_path, mtime_ns) for the directory itself, every entry
    directly inside its ``bin/`` subdirectory, and every directory matching
    ``.venv/lib/python*/site-packages`` (which catches torch-stack swaps
    that ``bin/`` would miss).  The relative paths are normalised to
    ``.venv``, ``.venv/bin/<name>`` and ``.venv/lib/python*/site-packages``
    so that the snapshot is independent of where the venv actually lives.
    """
    snapshot: list[tuple[str, int]] = []
    if venv_dir.exists():
        snapshot.append((".venv", venv_dir.stat().st_mtime_ns))
        bin_dir = venv_dir / "bin"
        if bin_dir.exists():
            for entry in bin_dir.iterdir():
                snapshot.append((".venv/bin/" + entry.name, entry.stat().st_mtime_ns))
        for site_dir in venv_dir.glob("lib/python*/site-packages"):
            if site_dir.is_dir():
                rel = ".venv/" + str(site_dir.relative_to(venv_dir))
                snapshot.append((rel, site_dir.stat().st_mtime_ns))
    return sorted(snapshot)


def _run_install(
    tmp_path: Path,
    flags: list[str],
    *,
    nvidia_cuda: str | None = None,
    rocm: bool = False,
    xpu: bool = False,
) -> tuple[subprocess.CompletedProcess, str]:
    """Run ``bash scripts/install.sh <flags>`` with a shimmed PATH.

    Returns ``(completed_process, pip_argv_log_text)``.  Every shim lives in
    ``tmp_path``; the pip shim absorbs every install attempt, so nothing is
    installed; the installer is pointed at a skeleton venv under ``tmp_path``
    and the network is never touched.  The returned exit status is deliberately
    never asserted by any case: the shimmed install can never satisfy
    install.sh's closing torch-import verification, so a non-zero exit is the
    correct outcome here.

    Steering:

    * ``nvidia_cuda=None`` writes a *present-but-failing* nvidia-smi shim —
      a CPU-only host.  The shim must exist even for that case: NVIDIA
      detection requires presence AND a working ``nvidia-smi -L``, and
      GPU-equipped test hosts carry a real nvidia-smi that PATH would
      otherwise fall through to.
    * ``nvidia_cuda="<version>"`` writes a succeeding nvidia-smi reporting
      that "CUDA Version" header.
    * ``rocm=True`` / ``xpu=True`` write succeeding ROCm/XPU shims.  When
      False, NO shim is written at all: ROCm and XPU are detected by presence
      alone (``command -v`` succeeds for any existing file, whatever its exit
      code), so a failing shim would still count as "present" — their absence
      is simulated by omission (see the module skipif for the host requirement).

    Guard: if the repository ``.venv`` is created or modified despite
    ``KAINE_VENV_DIR`` pointing at a skeleton venv under ``tmp_path``, the
    test fails so the developer's environment is never touched silently.
    """
    shim_dir = tmp_path / "shims"
    shim_dir.mkdir()
    log_path = tmp_path / "pip_argv.log"

    real_python3 = shutil.which("python3") or sys.executable

    pip_body = _PIP_SHIM.replace("@LOG@", str(log_path)).replace("@SHIM_DIR@", str(shim_dir))
    _write_shim(shim_dir / "pip", pip_body)
    _write_shim(shim_dir / "pip3", pip_body)

    if nvidia_cuda is None:
        # The one "absence" simulated by a shim: nvidia-smi must exist (to
        # shadow a real binary on GPU-equipped hosts) and must fail, which is
        # exactly how install.sh decides "not an NVIDIA host".
        _write_shim(shim_dir / "nvidia-smi", _NVIDIA_SMI_FAIL_SHIM)
    else:
        _write_shim(shim_dir / "nvidia-smi", _NVIDIA_SMI_OK_SHIM.replace("@CUDA@", nvidia_cuda))

    if rocm:
        _write_shim(shim_dir / "rocm-smi", _ROCM_SMI_OK_SHIM)
    # else: no rocm-smi shim at all.  install.sh detects ROCm by PRESENCE
    # (`command -v rocm-smi` succeeds whenever the file exists, whatever its
    # exit code), so a failing shim would still count as "present" and flip
    # the flavor to rocm — the mistake that once made this CPU-only case
    # receive the rocm6.2 index.  Absence is simulated by omission.

    if xpu:
        _write_shim(shim_dir / "sycl-ls", _SYCL_LS_OK_SHIM)
        _write_shim(shim_dir / "xpu-smi", _XPU_SMI_OK_SHIM)
    # else: no xpu-smi / sycl-ls shims at all — same presence-only detection.

    python_body = _PYTHON_SHIM.replace("@REAL_PYTHON3@", real_python3).replace(
        "@SHIM_DIR@", str(shim_dir)
    )
    _write_shim(shim_dir / "python3", python_body)
    _write_shim(shim_dir / "python", python_body)

    # A skeleton virtualenv for installers that honour an active VIRTUAL_ENV:
    # its pip/python are the same shims, so every pip invocation flavour is
    # absorbed and logged into the same per-case log file.
    venv_dir = tmp_path / "venv"
    (venv_dir / "bin").mkdir(parents=True)
    (venv_dir / "pyvenv.cfg").write_text(
        "home = {}\ninclude-system-site-packages = true\nversion = 3.11\n".format(
            os.path.dirname(real_python3)
        ),
        encoding="utf-8",
    )
    _write_shim(venv_dir / "bin" / "python", python_body)
    _write_shim(venv_dir / "bin" / "python3", python_body)
    _write_shim(venv_dir / "bin" / "pip", pip_body)
    _write_shim(venv_dir / "bin" / "pip3", pip_body)
    (venv_dir / "bin" / "activate").write_text("# no-op activate (test shim)\n", encoding="utf-8")

    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([str(shim_dir), env.get("PATH", "")])
    env["KAINE_VENV_DIR"] = str(venv_dir)
    env["VIRTUAL_ENV"] = str(venv_dir)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    inherited_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        os.pathsep.join([str(REPO_ROOT), inherited_pythonpath])
        if inherited_pythonpath
        else str(REPO_ROOT)
    )
    # Shadow any system-installed torch so install.sh's idempotency check
    # ("import torch" succeeds → "already installed" → skip pip install)
    # always falls through to the pip install step.  Without this, CI
    # runners that carry torch in their base environment never reach the
    # `pip install --index-url …` command the tests assert on.
    poison_dir = tmp_path / "poison"
    poison_dir.mkdir()
    (poison_dir / "torch").mkdir()
    (poison_dir / "torch" / "__init__.py").write_text(
        "raise ImportError('torch not installed (test shim)')\n",
        encoding="utf-8",
    )
    env["PYTHONPATH"] = os.pathsep.join([str(poison_dir), env["PYTHONPATH"]])

    repo_venv = REPO_ROOT / ".venv"
    repo_venv_before = _venv_snapshot(repo_venv)
    repo_pycache = REPO_ROOT / "kaine" / "__pycache__"
    repo_pycache_before = repo_pycache.exists()
    proc = None  # type: ignore[assignment]  # assigned inside try; pytest.fail always raises on timeout
    try:
        proc = subprocess.run(
            ["bash", "scripts/install.sh", *flags],
            cwd=str(REPO_ROOT),
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=RUN_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(
            "scripts/install.sh did not finish within {}s (stdout={!r}, stderr={!r})".format(
                RUN_TIMEOUT_SECONDS, exc.stdout, exc.stderr
            )
        )
    finally:
        repo_venv_after = _venv_snapshot(repo_venv)
        if not repo_venv_before and repo_venv_after:
            shutil.rmtree(repo_venv, ignore_errors=True)
            pytest.fail(
                f"scripts/install.sh created {repo_venv} despite "
                f"KAINE_VENV_DIR pointing to a skeleton venv under tmp_path"
            )
        if repo_venv_before and repo_venv_before != repo_venv_after:
            pytest.fail(
                f"scripts/install.sh modified the repository venv {repo_venv}: "
                f"before={repo_venv_before!r} after={repo_venv_after!r}"
            )
        if not repo_pycache_before and repo_pycache.exists():
            shutil.rmtree(repo_pycache, ignore_errors=True)

    pip_log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    return proc, pip_log


def test_cpu_only_host_pip_receives_cpu_index(tmp_path: Path) -> None:
    """Case 1 — a host with no accelerator tooling gets the CPU index.

    Invariant: with nvidia-smi present-but-failing and NO rocm-smi, xpu-smi or
    sycl-ls shim written at all, install.sh behaves exactly as on a CPU-only
    machine and pip receives --index-url https://download.pytorch.org/whl/cpu
    — and never a CUDA, ROCm or XPU index.  The asymmetry is deliberate and
    mirrors the installer's detection semantics: NVIDIA requires presence AND
    a working ``nvidia-smi -L``, so a present-but-failing shim is exactly "no
    NVIDIA host" — and it must exist, because GPU-equipped test hosts (e.g.
    the aarch64 Jetson) carry a real nvidia-smi that PATH would otherwise fall
    through to.  ROCm and XPU are detected by PRESENCE alone (``command -v``
    succeeds for any existing file, whatever its exit code), so a failing shim
    would still count as "present" — their absence is simulated by omission.
    Cost prevented: a CUDA wheel index leaking onto accelerator-less hosts,
    where pip would pull gigabytes of CUDA dependencies that can never be used.

    The non-zero exit is expected and deliberately not asserted: the pip shim
    absorbs the install without installing anything, so install.sh's closing
    torch-import verification cannot succeed.
    """
    proc, pip_log = _run_install(tmp_path, [])
    urls = _index_urls(pip_log)
    assert set(urls) == {CPU_INDEX}, _context(proc, pip_log)


def test_cpu_flag_beats_nvidia_smi_and_skips_resolver(tmp_path: Path) -> None:
    """Case 2 — --cpu wins over a successful nvidia-smi; the resolver is not consulted.

    Invariant: an explicit --cpu serves the CPU index even where nvidia-smi
    succeeds, and the CUDA wheel-index resolver is never consulted — none of
    its JSON ("index_url", "selected_reason") may appear on stdout/stderr.
    Cost prevented: dragging CUDA wheels and their multi-gigabyte dependency
    set onto a host the operator explicitly pinned to CPU, plus pointless
    resolver probing on that host.

    The non-zero exit is expected and deliberately not asserted: the pip shim
    absorbs the install without installing anything, so install.sh's closing
    torch-import verification cannot succeed.
    """
    proc, pip_log = _run_install(tmp_path, ["--cpu"], nvidia_cuda="12.8")
    urls = _index_urls(pip_log)
    assert set(urls) == {CPU_INDEX}, _context(proc, pip_log)
    combined_output = proc.stdout + proc.stderr
    assert "index_url" not in combined_output, _context(proc, pip_log)
    assert "selected_reason" not in combined_output, _context(proc, pip_log)


def test_rocm_flag_keeps_prechange_rocm_index(tmp_path: Path) -> None:
    """Case 3 — --rocm keeps the byte-identical pre-change ROCm index.

    Invariant: host-aware wheel-index resolution is scoped to the CUDA flavor;
    --rocm still sends pip to https://download.pytorch.org/whl/rocm6.2 exactly
    (the pre-change constant, asserted byte for byte).  Cost prevented:
    silently repointing working ROCm installs at a different wheel index and
    breaking environments that already work.

    The non-zero exit is expected and deliberately not asserted: the pip shim
    absorbs the install without installing anything, so install.sh's closing
    torch-import verification cannot succeed.
    """
    proc, pip_log = _run_install(tmp_path, ["--rocm"], rocm=True)
    urls = _index_urls(pip_log)
    assert set(urls) == {ROCM_INDEX}, _context(proc, pip_log)


def test_xpu_flag_gets_dedicated_xpu_index(tmp_path: Path) -> None:
    """Case 4 — --xpu keeps its dedicated index.

    Invariant: the XPU flavor sends pip to
    https://download.pytorch.org/whl/xpu and nothing else; CUDA resolution
    must not leak into it.  Cost prevented: XPU hosts silently receiving CUDA
    (or CPU) wheels that cannot use the Intel GPU.

    The non-zero exit is expected and deliberately not asserted: the pip shim
    absorbs the install without installing anything, so install.sh's closing
    torch-import verification cannot succeed.
    """
    proc, pip_log = _run_install(tmp_path, ["--xpu"], xpu=True)
    urls = _index_urls(pip_log)
    assert set(urls) == {XPU_INDEX}, _context(proc, pip_log)


def test_mps_flag_adds_no_index_url(tmp_path: Path) -> None:
    """Case 5 — --mps adds no --index-url at all; the MPS wheel comes from PyPI.

    Invariant: even on a host where nvidia-smi succeeds, the --mps flavor must
    not point pip at any pytorch.org index — pip is still invoked, but without
    --index-url.  Cost prevented: pointing the MPS install at an index that
    carries no MPS wheel, failing the install outright.

    The non-zero exit is expected and deliberately not asserted: the pip shim
    absorbs the install without installing anything, so install.sh's closing
    torch-import verification cannot succeed.
    """
    proc, pip_log = _run_install(tmp_path, ["--mps"], nvidia_cuda="12.8")
    assert pip_log.strip(), _context(proc, pip_log)  # pip was invoked at all
    assert _index_urls(pip_log) == [], _context(proc, pip_log)


def test_operator_index_url_override_wins_for_cuda(tmp_path: Path) -> None:
    """Case 6 — --index-url with --cuda reaches pip verbatim: the override wins.

    Invariant: an explicit operator --index-url is passed to pip exactly as
    given, replacing whatever host-based resolution would have chosen for the
    steered host (nvidia-smi reporting a CUDA 12.8 driver).  Cost prevented:
    an operator-pinned index (internal mirror, vetted snapshot) being silently
    swapped for the resolved public index.

    The non-zero exit is expected and deliberately not asserted: the pip shim
    absorbs the install without installing anything, so install.sh's closing
    torch-import verification cannot succeed.
    """
    proc, pip_log = _run_install(
        tmp_path, ["--cuda", "--index-url", OVERRIDE_INDEX], nvidia_cuda="12.8"
    )
    urls = _index_urls(pip_log)
    assert urls and set(urls) == {OVERRIDE_INDEX}, _context(proc, pip_log)


def test_index_url_override_ignored_for_cpu_with_notice(tmp_path: Path) -> None:
    """Case 7 — --index-url is ignored for --cpu, with a notice naming the flavor.

    Invariant: the CPU flavor owns its index, so pip still receives the CPU
    index and never the override; stderr carries a notice that the override
    was ignored, and that notice names the flavor actually used — 'cpu' in
    the quoted flavor-name position, never the literal word 'flavor' there
    (the shipped quoting bug once emitted ``for flavor 'flavor'``).  The bare
    word "flavor" legitimately appears as a noun in the notice text, so the
    regression guard forbids only the quoted-name form.  Cost prevented:
    operators being told an override was ignored when it had been honoured —
    or the reverse — and debugging the wrong layer.

    The non-zero exit is expected and deliberately not asserted: the pip shim
    absorbs the install without installing anything, so install.sh's closing
    torch-import verification cannot succeed.
    """
    proc, pip_log = _run_install(
        tmp_path, ["--cpu", "--index-url", OVERRIDE_INDEX], nvidia_cuda="12.8"
    )
    urls = _index_urls(pip_log)
    assert set(urls) == {CPU_INDEX}, _context(proc, pip_log)
    stderr = proc.stderr.lower()
    assert "ignor" in stderr, _context(proc, pip_log)
    assert "cpu" in stderr, _context(proc, pip_log)
    # Regression guard for the shipped quoting bug: the notice once named the
    # placeholder itself ("... for flavor 'flavor' ...").  The bare word
    # "flavor" is legitimate noun text in the notice, so only the quoted
    # flavor-name form is forbidden.
    assert "'flavor'" not in stderr, _context(proc, pip_log)


def test_index_url_override_wins_over_host_resolution(tmp_path: Path) -> None:
    """Case 8 — --cuda with --index-url on a host whose probes resolve differently.

    Invariant: host-aware resolution only fills the gap when the operator has
    not made a choice.  With nvidia-smi reporting a CUDA 13.x driver the
    probes would pick a different pytorch.org index (cu130 on x86_64; on the
    aarch64 Tegra host, exhaustion routes to the CPU index) — yet pip must
    receive exactly the operator's URL.  Cost prevented: the resolver
    clobbering a deliberately pinned index on any host shape.

    The non-zero exit is expected and deliberately not asserted: the pip shim
    absorbs the install without installing anything, so install.sh's closing
    torch-import verification cannot succeed.
    """
    proc, pip_log = _run_install(
        tmp_path, ["--cuda", "--index-url", OVERRIDE_INDEX], nvidia_cuda="13.2"
    )
    urls = _index_urls(pip_log)
    assert urls and set(urls) == {OVERRIDE_INDEX}, _context(proc, pip_log)


def test_torch_and_torchvision_installed_together(tmp_path: Path) -> None:
    """The torch install step passes torch and torchvision together from one index."""
    proc, pip_log = _run_install(tmp_path, ["--cpu", "--no-wizard"])
    for line in pip_log.splitlines():
        tokens = line.split()
        has_torch = any(t.startswith(("torch>=", "torch==", "torch<")) for t in tokens)
        has_tv = "torchvision" in tokens
        has_cpu_index = "--index-url" in tokens and CPU_INDEX in tokens
        if has_torch and has_tv and has_cpu_index:
            return
    pytest.fail(
        "no recorded pip invocation installed torch and torchvision together "
        f"from {CPU_INDEX!r}" + _context(proc, pip_log)
    )


def test_later_installs_are_constrained(tmp_path: Path) -> None:
    """Every editable install receives the torch stack constraints file."""
    proc, pip_log = _run_install(tmp_path, ["--cpu", "--no-wizard"])
    lines = pip_log.splitlines()
    assert any("-e" in line.split() for line in lines), _context(proc, pip_log)
    for line in lines:
        tokens = line.split()
        if "-e" not in tokens:
            continue
        if "-c" not in tokens:
            pytest.fail(f"pip line with -e lacks -c: {line!r}" + _context(proc, pip_log))
        c_idx = tokens.index("-c")
        if c_idx + 1 >= len(tokens) or not tokens[c_idx + 1].endswith(
            "kaine-torch-constraints.txt"
        ):
            pytest.fail(
                f"pip line with -e has no kaine-torch-constraints.txt after -c: {line!r}"
                + _context(proc, pip_log)
            )


def test_install_proceeds_past_constraints_to_editable_install(tmp_path: Path) -> None:
    """The installer reaches the editable install after writing constraints.

    Regression guard for the empty-constraints-file crash: with the pip shim
    absorbing every install, the constraints file is empty, but the script
    must not abort and must still invoke ``pip install -e ".[test]"``.
    """
    proc, pip_log = _run_install(tmp_path, ["--cpu", "--no-wizard"])
    for line in pip_log.splitlines():
        tokens = line.split()
        if "-e" in tokens and ".[test]" in tokens:
            return
    pytest.fail(
        "no recorded pip invocation contained both -e and '.[test]'"
        + _context(proc, pip_log)
    )


def test_print_torch_spec_matches_pyproject() -> None:
    """--print-torch-spec emits the torch dependency from pyproject.toml."""
    import tomllib

    with open(REPO_ROOT / "pyproject.toml", "rb") as f:
        deps = tomllib.load(f)["project"]["dependencies"]
    operators = ("~=", "==", "!=", "<=", ">=", ">", "<")
    expected = next(
        dep
        for dep in deps
        if dep.startswith("torch")
        and any(dep[len("torch") :].lstrip().startswith(op) for op in operators)
    )
    proc = subprocess.run(
        ["bash", "scripts/install.sh", "--print-torch-spec"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        errors="replace",
        timeout=RUN_TIMEOUT_SECONDS,
    )
    assert proc.returncode == 0, (
        f"install.sh --print-torch-spec exited {proc.returncode}\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    )
    assert proc.stdout.strip() == expected, (
        f"expected {expected!r}, got {proc.stdout.strip()!r}\n"
        f"stderr: {proc.stderr}"
    )
