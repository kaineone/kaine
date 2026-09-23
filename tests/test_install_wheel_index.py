# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Integration tests: ``scripts/install.sh`` must hand pip the right ``--index-url``.

``scripts/install.sh`` used to hardcode the NVIDIA cu128 wheel index and the
ROCm rocm6.2 wheel index, using them blindly on every host where the
corresponding accelerator tooling succeeded — ignoring CPU architecture, the
driver's CUDA version, the GPU's compute capability, and the ROCm stack/gfx
targets.  On aarch64 the CUDA index serves SBSA wheels built for sm_90/sm_100:
they import cleanly and then die at the FIRST KERNEL LAUNCH with "no kernel
image is available for execution on the device" — the worst failure mode,
because install and configuration both appeared to succeed.  The installer now
resolves the wheel index from the host (``kaine/wheel_index.py``) for both CUDA
and ROCm flavors and this module is the evidence that

  (a) the resolved index actually reaches pip as ``--index-url``,
  (b) an explicit operator ``--index-url`` override wins where it must win,
  (c) the override is ignored — with a notice naming the flavor — where it
      must be ignored,
  (d) the non-resolved flavors (``--cpu``/``--xpu``/``--mps``) were not
      disturbed by the CUDA change, and
  (e) ``--rocm`` now resolves via the host-aware resolver and exits with a
      clear error when no wheel index serves the detected ROCm stack.

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
wheel-index resolver: the ``python3``/``python`` shims delegate everything to the
real interpreter except ``-m venv`` (a skeleton virtualenv is fabricated —
no ensurepip, no network, no real venv anywhere), ``-m pip`` (routed to the pip
shim, so it absorbs every install attempt), and ``-m kaine.wheel_index``
(which can be forced to mark the resolved stack as requiring a GPU self-test
when ``KAINE_TEST_FORCE_SELFTEST`` is set to ``1``, so the fallback path is
exercised).

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

import json
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
ROCM62_INDEX = "https://download.pytorch.org/whl/rocm6.2"
ROCM72_INDEX = "https://download.pytorch.org/whl/rocm7.2"
XPU_INDEX = "https://download.pytorch.org/whl/xpu"
CUDA132_INDEX = "https://download.pytorch.org/whl/cu132"
CUDA130_INDEX = "https://download.pytorch.org/whl/cu130"
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
  uninstall)
    # Absorb uninstalls so the installer can record the command.
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

_ROCM_INFO_SAMPLE_SHIM = r"""#!/bin/sh
# Test shim: rocminfo with iGPU, dGPU, a generic name and gfx000.
printf '  Name: gfx1036\n'
printf '  Name: gfx1100\n'
printf '  Name: gfx11-generic\n'
printf '  Name: gfx000\n'
printf '  Name: gfx1100\n'
exit 0
"""

_ROCM_INFO_EXIT1_SHIM = r"""#!/bin/sh
# Test shim: rocminfo prints a usable gfx name and exits non-zero.
# The installer must keep the parsed name and continue, not abort under set -e.
printf '  Name: gfx1100\n'
exit 1
"""

_ROCM_INFO_SUFFIX_SHIM = r"""#!/bin/sh
# Test shim: rocminfo names carry feature suffixes.
printf '  Name: gfx90a:xnack-\n'
printf '  Name: gfx90a:sramecc+:xnack-\n'
printf '  Name: gfx000\n'
printf '  Name: gfx11-generic\n'
printf '  Name: gfx90a:xnack-\n'
exit 0
"""

_ROCM_AGENT_SUFFIX_SHIM = r"""#!/bin/sh
# Test shim: rocm_agent_enumerator names carry feature suffixes.
printf 'gfx90a:xnack-\n'
printf 'gfx90a:sramecc+:xnack-\n'
printf 'gfx000\n'
printf 'gfx11-generic\n'
printf 'gfx90a:xnack-\n'
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
# only it) runs the wheel-index resolver.  Exceptions keep the test hermetic:
# `-m venv` fabricates a skeleton virtualenv (no ensurepip, no network, no
# real venv anywhere); `-m pip` is routed to the pip shim; `-m kaine.wheel_index`
# can be forced to request a GPU self-test when KAINE_TEST_FORCE_SELFTEST is
# set to 1.
REAL='@REAL_PYTHON3@'
SHIM_DIR='@SHIM_DIR@'
state=0
is_venv=0
is_wheel_index=0
target=''
for arg in "$@"; do
  case "$state" in
    0)
      if [ "$arg" = '-m' ]; then state=1; fi
      ;;
    1)
      case "$arg" in
        venv) is_venv=1; state=2 ;;
        kaine.wheel_index) is_wheel_index=1; state=0 ;;
        *) state=0 ;;
      esac
      ;;
    2)
      case "$arg" in
        -*) : ;;
        *) if [ -z "$target" ]; then target="$arg"; fi ;;
      esac
      ;;
  esac
done

if [ "$is_wheel_index" = '1' ] && [ "${KAINE_TEST_FORCE_SELFTEST:-}" = '1' ]; then
  output=$("$REAL" "$@" 2>/dev/null)
  rc=$?
  if [ "$rc" -eq 0 ] && [ -n "$output" ]; then
    printf '%s\n' "$output" | "$REAL" -c 'import json,sys; d=json.load(sys.stdin); d["selftest_required"]=True; print(json.dumps(d))'
    exit 0
  fi
  printf '%s\n' "$output"
  exit "$rc"
fi

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

_FAKE_TORCH_CPU = '''\
__version__ = "2.14.0+cpu"


class version:
    hip = None


class cuda:
    @staticmethod
    def is_available():
        return False


class _mps:
    @staticmethod
    def is_available():
        return False


class backends:
    mps = _mps()


__all__ = ["__version__", "version", "cuda", "backends"]
'''


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
        f"\ninstaller exit code: {proc.returncode}"
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
    installer: str = "install.sh",
    nvidia_cuda: str | None = None,
    rocm: bool = False,
    rocminfo_sample: bool = False,
    rocminfo_exit1: bool = False,
    rocminfo_suffix: bool = False,
    rocm_agent_suffix: bool = False,
    xpu: bool = False,
    fake_torch: str | None = None,
    fake_torchaudio: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess, str]:
    """Run ``bash scripts/install.sh <flags>`` or ``python scripts/install.py
    <flags>`` with a shimmed PATH.

    Returns ``(completed_process, pip_argv_log_text)``.  Every shim lives in
    ``tmp_path``; the pip shim absorbs every install attempt, so nothing is
    installed; the installer is pointed at a skeleton venv under ``tmp_path``
    and the network is never touched.  The returned exit status is deliberately
    never asserted by any case: the shimmed install can never satisfy
    the closing torch-import verification, so a non-zero exit is the
    correct outcome here.

    Steering:

    * ``nvidia_cuda=None`` writes a *present-but-failing* nvidia-smi shim —
      a CPU-only host.  The shim must exist even for that case: NVIDIA
      detection requires presence AND a working ``nvidia-smi -L``, and
      GPU-equipped test hosts carry a real nvidia-smi that PATH would
      otherwise fall through to.
    * ``nvidia_cuda="<version>"`` writes a succeeding nvidia-smi reporting
      that "CUDA Version" header.
    * ``rocm=True`` writes a succeeding rocm-smi shim.  ``rocminfo_sample=True``
      also writes a rocminfo shim that emits the gfx1036/gfx1100/gfx11-generic
      /gfx000 sample so bash gfx parsing is exercised.
    * ``xpu=True`` writes succeeding sycl-ls and xpu-smi shims.
    * ``fake_torch="cpu"`` puts a fake CPU-flavor torch package at the front of
      PYTHONPATH so the installer's flavor probe reports a CPU wheel installed.
    * ``fake_torchaudio="<version>"`` puts a fake torchaudio distribution at the
      front of PYTHONPATH so the installer sees a stale torchaudio.
    * ``extra_env`` is merged into the test environment after the base copy,
      so callers can set ``KAINE_ROCM_VERSION``/``KAINE_ROCM_GFX`` etc.

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

    if rocminfo_exit1:
        _write_shim(shim_dir / "rocminfo", _ROCM_INFO_EXIT1_SHIM)
    elif rocminfo_suffix:
        _write_shim(shim_dir / "rocminfo", _ROCM_INFO_SUFFIX_SHIM)
    elif rocminfo_sample:
        _write_shim(shim_dir / "rocminfo", _ROCM_INFO_SAMPLE_SHIM)
    # else: no rocminfo shim at all.

    if rocm_agent_suffix:
        _write_shim(shim_dir / "rocm_agent_enumerator", _ROCM_AGENT_SUFFIX_SHIM)
    # else: no rocm_agent_enumerator shim at all.

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
    if extra_env is not None:
        env.update(extra_env)
    env["PATH"] = os.pathsep.join([str(shim_dir), env.get("PATH", "")])
    env["KAINE_VENV_DIR"] = str(venv_dir)
    env["VIRTUAL_ENV"] = str(venv_dir)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["KAINE_WHEEL_PROBE_NVML"] = "0"
    inherited_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        os.pathsep.join([str(REPO_ROOT), inherited_pythonpath])
        if inherited_pythonpath
        else str(REPO_ROOT)
    )

    # PYTHONPATH front: a fake torch package (or an ImportError poison) and an
    # optional fake torchaudio distribution.  These are seen by the real
    # interpreter that the shim delegates to.
    poison_dir = tmp_path / "poison"
    poison_dir.mkdir()
    torch_dir = poison_dir / "torch"
    torch_dir.mkdir()
    if fake_torch == "cpu":
        (torch_dir / "__init__.py").write_text(_FAKE_TORCH_CPU, encoding="utf-8")
    else:
        (torch_dir / "__init__.py").write_text(
            "raise ImportError('torch not installed (test shim)')\n",
            encoding="utf-8",
        )
    if fake_torchaudio is not None:
        ta_pkg = poison_dir / "torchaudio"
        ta_pkg.mkdir()
        (ta_pkg / "__init__.py").write_text("# fake torchaudio\n", encoding="utf-8")
        ta_dist = poison_dir / f"torchaudio-{fake_torchaudio}.dist-info"
        ta_dist.mkdir()
        (ta_dist / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: torchaudio\nVersion: {fake_torchaudio}\n",
            encoding="utf-8",
        )
    env["PYTHONPATH"] = os.pathsep.join([str(poison_dir), env["PYTHONPATH"]])

    repo_venv = REPO_ROOT / ".venv"
    repo_venv_before = _venv_snapshot(repo_venv)
    repo_pycache = REPO_ROOT / "kaine" / "__pycache__"
    repo_pycache_before = repo_pycache.exists()

    if installer == "install.sh":
        cmd: list[str] = ["bash", "scripts/install.sh", *flags]
    elif installer == "install.py":
        cmd = [sys.executable, str(REPO_ROOT / "scripts" / "install.py"), *flags]
    else:
        raise ValueError(f"unknown installer: {installer}")

    proc = None  # type: ignore[assignment]  # assigned inside try; pytest.fail always raises on timeout
    try:
        proc = subprocess.run(
            cmd,
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
            f"{installer} did not finish within {RUN_TIMEOUT_SECONDS}s "
            f"(stdout={exc.stdout!r}, stderr={exc.stderr!r})"
        )
    finally:
        repo_venv_after = _venv_snapshot(repo_venv)
        if not repo_venv_before and repo_venv_after:
            shutil.rmtree(repo_venv, ignore_errors=True)
            pytest.fail(
                f"{installer} created {repo_venv} despite "
                f"KAINE_VENV_DIR pointing to a skeleton venv under tmp_path"
            )
        if repo_venv_before and repo_venv_before != repo_venv_after:
            pytest.fail(
                f"{installer} modified the repository venv {repo_venv}: "
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


def test_rocm_flag_resolves_host_aware_rocm_index(tmp_path: Path) -> None:
    """Case 3 — --rocm now resolves the wheel index from the host.

    Invariant: the ROCm flavor runs ``kaine.wheel_index`` with the ROCm
    version and gfx targets, so pip receives the host-resolved index
    (rocm7.2 for the shimmed ROCm 7.2 / gfx1100 stack) and the exact pinned
    torch stack from that index.  Cost prevented: silently repointing working
    ROCm installs at a different wheel index and breaking environments that
    already work.

    The non-zero exit is expected and deliberately not asserted: the pip shim
    absorbs the install without installing anything, so install.sh's closing
    torch-import verification cannot succeed.
    """
    proc, pip_log = _run_install(
        tmp_path,
        ["--rocm"],
        rocm=True,
        extra_env={"KAINE_ROCM_VERSION": "7.2", "KAINE_ROCM_GFX": "gfx1100"},
    )
    urls = _index_urls(pip_log)
    assert set(urls) == {ROCM72_INDEX}, _context(proc, pip_log)
    assert any("torch==2.14.0" in line for line in pip_log.splitlines()), _context(
        proc, pip_log
    )


def test_rocm_unsupported_version_exits_with_tested_range_error(tmp_path: Path) -> None:
    """An unsupported ROCm stack exits before any pip torch install.

    Invariant: when the host-aware resolver cannot find a wheel index for the
    detected ROCm stack, install.sh exits with a clear error mentioning the
    project's tested range and never asks pip to install torch.
    """
    proc, pip_log = _run_install(
        tmp_path,
        ["--rocm"],
        rocm=True,
        extra_env={"KAINE_ROCM_VERSION": "6.2", "KAINE_ROCM_GFX": "gfx1100"},
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode != 0, _context(proc, pip_log)
    assert "tested range" in combined.lower(), _context(proc, pip_log)
    assert not any("torch" in line for line in pip_log.splitlines()), _context(
        proc, pip_log
    )


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


def test_cuda_132_resolves_pinned_torch_stack(tmp_path: Path) -> None:
    """A CUDA 13.2 host gets the exact pinned torch/torchvision from cu132."""
    proc, pip_log = _run_install(
        tmp_path, ["--cuda", "--no-wizard"], nvidia_cuda="13.2"
    )
    assert any(
        "torch==2.14.0" in line
        and "torchvision==0.29.0" in line
        and CUDA132_INDEX in line
        for line in pip_log.splitlines()
    ), _context(proc, pip_log)


def test_cuda_132_research_resolves_index_with_torchaudio(tmp_path: Path) -> None:
    """--research on a CUDA 13.2 host passes --need-torchaudio and falls to cu130."""
    proc, pip_log = _run_install(
        tmp_path, ["--cuda", "--no-wizard", "--research"], nvidia_cuda="13.2"
    )
    urls = _index_urls(pip_log)
    assert CUDA130_INDEX in urls, _context(proc, pip_log)
    lines = pip_log.splitlines()
    assert any("torchaudio==2.11.0" in line for line in lines), _context(proc, pip_log)
    assert any("torch==2.14.0" in line for line in lines), _context(proc, pip_log)


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


def test_selftest_fallback_writes_marker_and_force_reinstalls_cpu(tmp_path: Path) -> None:
    """A failing GPU self-test falls back to CPU wheels and records the marker.

    Invariant: when the resolver requests a GPU numerical self-test and it
    fails (here because torch is poisoned in the test harness), pip first
    installs the GPU torch stack, then force-reinstalls the CPU stack, and the
    installer writes ``kaine-accel-fallback.json`` naming the GPU index and
    torch version.  Later runs skip the GPU attempt while the marker matches.
    Cost prevented: repeated futile GPU installs and self-tests on hosts
    where the GPU wheels are known-bad.
    """
    proc, pip_log = _run_install(
        tmp_path,
        ["--cuda", "--no-wizard"],
        nvidia_cuda="13.2",
        extra_env={"KAINE_TEST_FORCE_SELFTEST": "1"},
    )
    lines = pip_log.splitlines()
    gpu_lines = [line for line in lines if CUDA132_INDEX in line and "torch==" in line]
    assert gpu_lines, _context(proc, pip_log)
    gpu_idx = lines.index(gpu_lines[0])
    later_lines = lines[gpu_idx + 1 :]
    cpu_force_lines = [
        line
        for line in later_lines
        if CPU_INDEX in line and "--force-reinstall" in line and "torch==" in line
    ]
    assert cpu_force_lines, _context(proc, pip_log)

    marker_file = tmp_path / "venv" / "kaine-accel-fallback.json"
    assert marker_file.exists(), _context(proc, pip_log)
    data = json.loads(marker_file.read_text(encoding="utf-8"))
    assert data["index_url"] == CUDA132_INDEX, _context(proc, pip_log)
    assert data["torch"] == "2.14.0", _context(proc, pip_log)
    # The harness poisons torch, so the self-test exits 2 (skipped), not 1.
    assert data["reason"] == "GPU numerical self-test could not run (exit 2)", _context(
        proc, pip_log
    )


def test_selftest_fallback_skip_gpu_when_marker_present(tmp_path: Path) -> None:
    """A matching marker makes the installer keep/switch to CPU wheels.

    Invariant: if ``kaine-accel-fallback.json`` already records a GPU self-test
    failure for the exact index/torch version the resolver just chose, the
    installer skips the GPU install and uses the CPU index, printing a notice
    that names the marker file and the ``--retry-gpu`` flag.
    """
    venv_dir = tmp_path / "venv"
    marker_file = venv_dir / "kaine-accel-fallback.json"
    marker_file.parent.mkdir(parents=True, exist_ok=True)
    marker_file.write_text(
        json.dumps(
            {
                "reason": "GPU numerical self-test failed",
                "index_url": CUDA132_INDEX,
                "torch": "2.14.0",
                "date": "2026-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    proc, pip_log = _run_install(
        tmp_path,
        ["--cuda", "--no-wizard"],
        nvidia_cuda="13.2",
        extra_env={"KAINE_TEST_FORCE_SELFTEST": "0"},
    )
    urls = _index_urls(pip_log)
    assert CUDA132_INDEX not in urls, _context(proc, pip_log)
    assert CPU_INDEX in urls, _context(proc, pip_log)
    combined = proc.stdout + proc.stderr
    assert str(marker_file) in combined or "kaine-accel-fallback.json" in combined, _context(
        proc, pip_log
    )
    assert "--retry-gpu" in combined, _context(proc, pip_log)


def test_selftest_retry_gpu_removes_marker_and_attempts_gpu(tmp_path: Path) -> None:
    """--retry-gpu deletes the marker and lets the installer attempt the GPU index."""
    venv_dir = tmp_path / "venv"
    marker_file = venv_dir / "kaine-accel-fallback.json"
    marker_file.parent.mkdir(parents=True, exist_ok=True)
    marker_file.write_text(
        json.dumps(
            {
                "reason": "GPU numerical self-test failed",
                "index_url": CUDA132_INDEX,
                "torch": "2.14.0",
                "date": "2026-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    proc, pip_log = _run_install(
        tmp_path,
        ["--cuda", "--no-wizard", "--retry-gpu"],
        nvidia_cuda="13.2",
        extra_env={"KAINE_TEST_FORCE_SELFTEST": "0"},
    )
    urls = _index_urls(pip_log)
    assert CUDA132_INDEX in urls, _context(proc, pip_log)
    assert not marker_file.exists(), _context(proc, pip_log)


def test_flavor_switch_uses_force_reinstall(tmp_path: Path) -> None:
    """Switching from a CPU wheel to a CUDA wheel at the same version forces reinstall.

    Invariant: pip treats ``2.14.0+cpu`` as satisfying ``torch==2.14.0`` and
    will not swap to a CUDA wheel unless the installer passes
    ``--force-reinstall``.  With a fake CPU-flavor torch installed, the target
    CUDA index (cu132) is reached with ``--force-reinstall``.
    """
    proc, pip_log = _run_install(
        tmp_path,
        ["--cuda", "--no-wizard"],
        nvidia_cuda="13.2",
        fake_torch="cpu",
    )
    lines = pip_log.splitlines()
    cuda_lines = [line for line in lines if CUDA132_INDEX in line and "torch==" in line]
    assert cuda_lines, _context(proc, pip_log)
    assert all("--force-reinstall" in line for line in cuda_lines), _context(proc, pip_log)


def test_stale_torchaudio_is_uninstalled(tmp_path: Path) -> None:
    """A stale torchaudio is uninstalled before the constraints file is written.

    Invariant: when a torchaudio version that does not match the resolved
    research pin is already present, the installer emits
    ``pip uninstall -y torchaudio`` before writing constraints, so the stale
    pin can never leak into ``kaine-torch-constraints.txt``.
    """
    proc, pip_log = _run_install(
        tmp_path,
        ["--cuda", "--no-wizard", "--research"],
        nvidia_cuda="13.2",
        fake_torchaudio="2.10.0",
    )
    lines = pip_log.splitlines()
    assert any("uninstall -y torchaudio" in line for line in lines), _context(proc, pip_log)


def test_rocm_gfx_parsing_from_rocminfo_filters_igpu_generic_and_gfx000(tmp_path: Path) -> None:
    """The ROCm flavor parses rocminfo, filters iGPU/generic/gfx000, and resolves.

    Invariant: with the rocminfo sample shim that emits gfx1036, gfx1100,
    gfx11-generic and gfx000, the installer keeps only the real targets,
    prints them in the ROCm version line, and resolves the host-aware
    rocm7.2 index.
    """
    proc, pip_log = _run_install(
        tmp_path,
        ["--rocm"],
        rocm=True,
        rocminfo_sample=True,
        extra_env={"KAINE_ROCM_VERSION": "7.2"},
    )
    urls = _index_urls(pip_log)
    assert set(urls) == {ROCM72_INDEX}, _context(proc, pip_log)
    combined = proc.stdout + proc.stderr
    assert "==> ROCm version:" in combined, _context(proc, pip_log)
    assert "gfx1036" in combined, _context(proc, pip_log)
    assert "gfx1100" in combined, _context(proc, pip_log)
    assert "gfx11-generic" not in combined, _context(proc, pip_log)
    assert "gfx000" not in combined, _context(proc, pip_log)


def test_matching_torchaudio_with_local_tag_is_not_uninstalled(tmp_path: Path) -> None:
    """A torchaudio whose base version and tag match the resolved pin is kept.

    Invariant: an installed ``torchaudio==2.11.0+cu130`` satisfies the cu130
    research pin (base 2.11.0, tag cu130) and must not be uninstalled; pip
    must still receive the research ``torchaudio==2.11.0`` install line.
    """
    proc, pip_log = _run_install(
        tmp_path,
        ["--cuda", "--no-wizard", "--research"],
        nvidia_cuda="13.2",
        fake_torchaudio="2.11.0+cu130",
    )
    lines = pip_log.splitlines()
    assert not any("uninstall -y torchaudio" in line for line in lines), _context(
        proc, pip_log
    )
    assert any("torchaudio==2.11.0" in line for line in lines), _context(proc, pip_log)


JETSON_CU130_INDEX = "https://pypi.jetson-ai-lab.io/jp7/cu130"


@pytest.mark.parametrize("installer", ["install.sh", "install.py"])
def test_cuda_132_plain_with_torchaudio_resolves_cu130_coherently(
    tmp_path: Path, installer: str
) -> None:
    """A plain CUDA run with torchaudio installed stays on an index carrying it.

    Invariant: when torchaudio is already present and --research is not given,
    the installer resolves with --need-torchaudio. On a driver CUDA 13.2 host
    that means cu130 (cu132 carries no torchaudio), the matching torchaudio is
    kept, and the audio-stack coherence notice is printed.
    """
    proc, pip_log = _run_install(
        tmp_path,
        ["--cuda", "--no-wizard"],
        installer=installer,
        nvidia_cuda="13.2",
        fake_torchaudio="2.11.0+cu130",
    )
    urls = _index_urls(pip_log)
    lines = pip_log.splitlines()
    assert CUDA130_INDEX in urls, _context(proc, pip_log)
    assert not any("uninstall -y torchaudio" in line for line in lines), _context(
        proc, pip_log
    )
    assert (
        "torchaudio is installed; keeping the audio stack coherent"
        in proc.stdout + proc.stderr
    ), _context(proc, pip_log)


@pytest.mark.parametrize("installer", ["install.sh", "install.py"])
def test_non_pytorch_index_url_forces_reinstall_on_flavor_mismatch(
    tmp_path: Path, installer: str
) -> None:
    """A non-PyTorch --index-url still forces reinstall when the flavor differs.

    Invariant: a fake CPU-flavor torch already installed satisfies the bare
    torch spec, so pip would not swap to the requested CUDA index without
    --force-reinstall. The installer must add --force-reinstall even when the
    target URL is not on download.pytorch.org.
    """
    proc, pip_log = _run_install(
        tmp_path,
        ["--cuda", "--index-url", JETSON_CU130_INDEX, "--no-wizard"],
        installer=installer,
        nvidia_cuda="13.2",
        fake_torch="cpu",
    )
    torch_lines = [
        line
        for line in pip_log.splitlines()
        if "torch==" in line and JETSON_CU130_INDEX in line
    ]
    assert torch_lines, _context(proc, pip_log)
    assert all("--force-reinstall" in line for line in torch_lines), _context(
        proc, pip_log
    )


def test_no_force_reinstall_for_untagged_cpu_wheel_on_cpu_index(tmp_path: Path) -> None:
    """An untagged (PyPI-style) torch wheel is not force-reinstalled for --cpu.

    Invariant: an installed wheel with no local tag is treated as ``cpu``; when
    the target index is also ``cpu`` the tag rule does not force a reinstall.
    The fake torch here reports flavor ``cpu`` and version ``2.14.0`` with no
    ``+`` tag, so the installer skips the torch install entirely.
    """
    proc, pip_log = _run_install(
        tmp_path,
        ["--cpu", "--no-wizard"],
        fake_torch="cpu",
    )
    lines = pip_log.splitlines()
    assert not any("--force-reinstall" in line for line in lines), _context(proc, pip_log)
    assert not any("torch==" in line for line in lines), _context(proc, pip_log)


def test_rocminfo_nonzero_exit_does_not_silently_abort(tmp_path: Path) -> None:
    """A rocminfo that prints a gfx name and exits non-zero is not fatal.

    Invariant: under ``set -euo pipefail`` the command substitution parsing
    ``rocminfo`` must not make the installer exit silently; the parsed name
    is kept and the installer reaches the ROCm version line.
    """
    proc, pip_log = _run_install(
        tmp_path,
        ["--rocm"],
        rocm=True,
        rocminfo_exit1=True,
        extra_env={"KAINE_ROCM_VERSION": "7.2"},
    )
    combined = proc.stdout + proc.stderr
    assert "==> ROCm version:" in combined, _context(proc, pip_log)
    assert set(_index_urls(pip_log)) == {ROCM72_INDEX}, _context(proc, pip_log)


def test_rocminfo_feature_suffixes_are_stripped(tmp_path: Path) -> None:
    """rocminfo parsing strips gfx feature suffixes before filtering."""
    proc, pip_log = _run_install(
        tmp_path,
        ["--rocm"],
        rocm=True,
        rocminfo_suffix=True,
        extra_env={"KAINE_ROCM_VERSION": "7.2"},
    )
    combined = proc.stdout + proc.stderr
    assert "gfx90a" in combined, _context(proc, pip_log)
    assert "xnack" not in combined, _context(proc, pip_log)
    assert "sramecc" not in combined, _context(proc, pip_log)
    assert "gfx000" not in combined, _context(proc, pip_log)
    assert "gfx11-generic" not in combined, _context(proc, pip_log)
    assert set(_index_urls(pip_log)) == {ROCM72_INDEX}, _context(proc, pip_log)


def test_rocm_agent_feature_suffixes_are_stripped(tmp_path: Path) -> None:
    """rocm_agent_enumerator parsing strips gfx feature suffixes before filtering."""
    proc, pip_log = _run_install(
        tmp_path,
        ["--rocm"],
        rocm=True,
        rocm_agent_suffix=True,
        extra_env={"KAINE_ROCM_VERSION": "7.2"},
    )
    combined = proc.stdout + proc.stderr
    assert "gfx90a" in combined, _context(proc, pip_log)
    assert "xnack" not in combined, _context(proc, pip_log)
    assert "sramecc" not in combined, _context(proc, pip_log)
    assert "gfx000" not in combined, _context(proc, pip_log)
    assert "gfx11-generic" not in combined, _context(proc, pip_log)
    assert set(_index_urls(pip_log)) == {ROCM72_INDEX}, _context(proc, pip_log)


def test_research_refused_when_torchaudio_unavailable_for_override(tmp_path: Path) -> None:
    """--research with an index that has no torchaudio exits before installing torch.

    Invariant: when the resolver reports ``torchaudio_unavailable`` for the
    chosen operator --index-url and --research is set, the installer exits
    non-zero before any ``pip install torch`` line and prints the required
    guidance.
    """
    proc, pip_log = _run_install(
        tmp_path,
        ["--cuda", "--no-wizard", "--research", "--index-url", CUDA132_INDEX],
        nvidia_cuda="13.2",
    )
    assert proc.returncode != 0, _context(proc, pip_log)
    combined = proc.stdout + proc.stderr
    expected = (
        f"install: --research needs torchaudio, but {CUDA132_INDEX} publishes no "
        "torchaudio for torch 2.14.0; choose a different --index-url or drop --research"
    )
    assert expected in combined, _context(proc, pip_log)
    assert not any(
        "torch==" in line or "torch>=" in line for line in pip_log.splitlines()
    ), _context(proc, pip_log)


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
