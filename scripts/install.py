#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Python port of scripts/install.sh.

Use on hosts where Bash is not the canonical shell (macOS with zsh-only
operators, BSD variants). Behavior matches scripts/install.sh.

The virtualenv location is controlled by the ``KAINE_VENV_DIR`` environment
variable (default ``.venv``; relative paths resolve against the repo root).

The installer pins the installed torch stack (torch, torchvision and, with
``--research``, torchaudio) in ``$KAINE_VENV_DIR/kaine-torch-constraints.txt``
and passes that constraints file to every subsequent pip install, so later
editable installs cannot re-resolve torch from a different index.

On a host where the resolved CUDA wheels fail the GPU numerical self-test
(unified-memory devices), the installer falls back to CPU wheels and writes
``$KAINE_VENV_DIR/kaine-accel-fallback.json``. Later runs skip the GPU attempt
and keep CPU wheels while that file matches the resolved index/torch version.
Use ``--retry-gpu`` to delete the marker and attempt the GPU index again.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]

# Legacy hardcoded CUDA wheel index. Kept only as the documented
# fallback for when the host-aware resolver (kaine.wheel_index) is
# unavailable or fails; normal CUDA installs resolve per host instead.
# cu126 is the CUDA index with the widest driver compatibility that carries
# the project's torch floor (cu128 stops at torch 2.11); the host-aware
# resolver still chooses per host when it is available.
NVIDIA_INDEX_URL = "https://download.pytorch.org/whl/cu126"
XPU_INDEX_URL = "https://download.pytorch.org/whl/xpu"
CPU_INDEX_URL = "https://download.pytorch.org/whl/cpu"

# MPS uses the default PyPI wheel — no --index-url needed.
_INDEX_BY_FLAVOR: dict[str, str | None] = {
    "cuda": NVIDIA_INDEX_URL,
    "xpu": XPU_INDEX_URL,
    "cpu": CPU_INDEX_URL,
    "mps": None,
}
VALID_FLAVORS = set(_INDEX_BY_FLAVOR) | {"rocm"}

# Fallback regex for older Python or for callers that monkeypatch tomllib away.
# It matches a project.dependencies line whose name is literally "torch"
# followed by a version operator (so "torchvision..." cannot match).
_TORCH_DEP_RE = re.compile(r'^\s*"(torch[<>=!~][^"]*)"')


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def torch_spec(repo_root: Path) -> str:
    """Return the torch dependency line from ``<repo_root>/pyproject.toml``.

    Uses :mod:`tomllib` when available (Python 3.11+), otherwise falls back to
    a regex over the file text. Raises :class:`SystemExit` if no dependency
    whose name is ``torch`` followed by a version operator is found.
    """
    pyproject = repo_root / "pyproject.toml"
    if not pyproject.is_file():
        raise SystemExit(f"install.py: {pyproject} not found")

    if tomllib is not None:
        try:
            with pyproject.open("rb") as f:
                data = tomllib.load(f)
        except Exception as exc:
            raise SystemExit(f"install.py: could not parse {pyproject}: {exc}") from exc
        for dep in data.get("project", {}).get("dependencies") or []:
            if isinstance(dep, str) and re.match(r"^torch\s*[<>=!~]", dep):
                return dep

    # Fallback path: regex over the raw file text.
    try:
        text = pyproject.read_text(encoding="utf-8")
    except Exception as exc:
        raise SystemExit(f"install.py: could not read {pyproject}: {exc}") from exc
    for line in text.splitlines():
        m = _TORCH_DEP_RE.match(line)
        if m:
            return m.group(1)

    raise SystemExit(
        f'install.py: could not find a torch dependency (e.g. "torch>=2.0") in {pyproject}'
    )


_CONSTRAINTS_SCRIPT = '''\
import importlib.metadata as md
names = ["torch", "torchvision", "torchaudio"]
out_path = {out_path!r}
pins = []
with open(out_path, "w") as f:
    for name in names:
        try:
            ver = md.version(name)
            f.write(f"{{name}}=={{ver}}\\n")
            pins.append(f"{{name}}=={{ver}}")
        except md.PackageNotFoundError:
            pass
print(" ".join(pins) if pins else "(none installed)")
'''


def write_torch_constraints(py: Path, out: Path) -> str:
    """Write a constraints file for the installed torch stack.

    Runs the venv Python so it inspects the environment that actually owns
    the packages. Returns the human-readable pinned summary emitted by the
    helper.
    """
    script = _CONSTRAINTS_SCRIPT.format(out_path=str(out))
    out.parent.mkdir(parents=True, exist_ok=True)
    return subprocess.check_output([str(py), "-c", script], text=True).strip()


def _argv_index_override(argv: list[str] | None = None) -> str | None:
    """Return the ``--index-url`` value from the command line, if any.

    ``argparse`` owns the flag (it is registered on the installer's parser);
    this pre-scan only lets :func:`torch_index_url` honour the operator
    override from every call site -- installer, wizard and ``--print-index``
    -- without each of them having to thread it through. Returns ``None``
    when the flag is absent.
    """
    if argv is None:
        argv = sys.argv[1:]
    override: str | None = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--index-url" and i + 1 < len(argv):
            override = argv[i + 1]
            i += 1
        elif arg.startswith("--index-url="):
            override = arg.split("=", 1)[1]
        i += 1
    return override


def _python_for_resolver(venv_python: Path | None = None) -> Path | str:
    """Prefer the venv interpreter when one exists; otherwise the current one."""
    if venv_python is not None and venv_python.exists():
        return venv_python
    return sys.executable


def _run_resolver(
    args: list[str],
    venv_python: Path | None = None,
) -> tuple[str, str, int]:
    """Run ``python -m kaine.wheel_index <args>`` from the repo root.

    Returns ``(stdout, stderr, returncode)``. The repo root is injected into
    ``PYTHONPATH`` so the module can be resolved even from a freshly-created
    venv that has not yet installed KAINE.
    """
    root = _repo_root()
    python = _python_for_resolver(venv_python)
    env = os.environ.copy()
    pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{root}{os.pathsep}{pp}" if pp else str(root)
    cmd = [str(python), "-m", "kaine.wheel_index", *args]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=root,
            env=env,
        )
    except FileNotFoundError as exc:
        return "", f"resolver failed to run: {exc}", 1
    return proc.stdout, proc.stderr, proc.returncode


def _parse_resolver_result(stdout: str, stderr: str, rc: int) -> dict | None:
    """Parse the resolver's JSON stdout, returning ``None`` on failure."""
    if rc != 0 or not stdout.strip():
        return None
    try:
        return json.loads(stdout.strip())
    except json.JSONDecodeError:
        return None


def _extract_pins(data: dict | None) -> tuple[str | None, str | None, str | None, bool]:
    """Read torch/torchvision/torchaudio pins and the self-test flag.

    ``null`` in JSON and the literal string ``"None"`` both become Python
    ``None`` so the installer never treats the string ``"None"`` as a
    version.
    """
    if not data:
        return None, None, None, False

    def _value(key: str) -> str | None:
        val = data.get(key)
        if val is None or val == "None":
            return None
        return val

    return (
        _value("torch_version"),
        _value("torchvision_version"),
        _value("torchaudio_version"),
        bool(data.get("selftest_required")),
    )


def _index_tag(index_url: str | None) -> str:
    """Return the wheel build tag implied by a PyTorch wheel index URL.

    Examples: ``https://download.pytorch.org/whl/cu130`` -> ``"cu130"``;
    ``https://download.pytorch.org/whl/cpu/`` -> ``"cpu"``; ``None`` or an
    empty URL (MPS / default PyPI) -> ``""``.
    """
    if not index_url:
        return ""
    return index_url.rstrip("/").split("/")[-1]


def _is_pytorch_whl_url(index_url: str | None) -> bool:
    """True when ``index_url`` is a ``download.pytorch.org/whl/<tag>`` URL."""
    return bool(index_url and index_url.startswith("https://download.pytorch.org/whl/"))


def _installed_torch_tag(py: Path) -> str:
    """Return the local build tag of the installed torch wheel, if any."""
    try:
        out = subprocess.check_output(
            [
                str(py),
                "-c",
                "import torch; print(torch.__version__.split('+',1)[1] if '+' in torch.__version__ else '')",
            ],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except subprocess.CalledProcessError:
        return ""
    return out


def _installed_torch_base(py: Path) -> str | None:
    try:
        out = subprocess.check_output(
            [
                str(py),
                "-c",
                "import torch; print(torch.__version__.split('+',1)[0])",
            ],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except subprocess.CalledProcessError:
        return None
    return out or None


def _installed_package_version(py: Path, package: str) -> str | None:
    """Return the installed version of ``package`` in the venv, or ``None``."""
    try:
        out = subprocess.check_output(
            [
                str(py),
                "-c",
                f"import importlib.metadata as md; print(md.version({package!r}))",
            ],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except subprocess.CalledProcessError:
        return None
    return out or None


def _needs_force_reinstall(installed_tag: str, target_tag: str, index_url: str | None) -> bool:
    """True when the installed torch build tag must be forced to match the target.

    Tag comparisons are only meaningful for ``download.pytorch.org/whl/<tag>``
    URLs. An installed wheel with no local tag is treated as the ``cpu`` tag,
    so default PyPI / macOS / Jetson wheels are not force-reinstalled when the
    target index is ``cpu``.
    """
    if not _is_pytorch_whl_url(index_url):
        return False
    if not installed_tag:
        installed_tag = "cpu"
    return installed_tag != target_tag


def _accel_fallback_marker_path(venv_dir: Path) -> Path:
    return venv_dir / "kaine-accel-fallback.json"


def _read_accel_fallback_marker(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_accel_fallback_marker(
    path: Path, *, reason: str, index_url: str, torch: str
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "reason": reason,
        "index_url": index_url,
        "torch": torch,
        "date": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f)


def _marker_matches(
    marker: dict | None,
    *,
    index_url: str | None,
    torch_pin: str | None,
    installed_base: str | None,
) -> bool:
    if not marker or not index_url:
        return False
    marker_url = marker.get("index_url")
    marker_torch = marker.get("torch")
    target_torch = torch_pin or installed_base
    return bool(
        marker_url
        and marker_url == index_url
        and target_torch
        and marker_torch == target_torch
    )


def _torchaudio_should_uninstall(
    installed_ta: str | None, ta_pin: str | None, index_url: str | None
) -> bool:
    """Return True when an installed torchaudio must be removed before pinning.

    If no target torchaudio pin applies, any installed torchaudio is stale.
    If a pin applies, the installed base version must match and the installed
    local tag must match the target index tag under the same rule used for
    torch force-reinstall: an untagged wheel counts as ``cpu``, and tag checks
    are skipped entirely when the target URL is not a PyTorch wheel index.
    """
    if not installed_ta:
        return False
    if ta_pin is None:
        return True
    base, _, installed_tag = installed_ta.partition("+")
    if base != ta_pin:
        return True
    if not _is_pytorch_whl_url(index_url):
        return False
    if not installed_tag:
        installed_tag = "cpu"
    target_tag = _index_tag(index_url)
    return installed_tag != target_tag


def _resolve_cuda_index(
    research: bool,
    override: str | None,
    venv_python: Path | None = None,
    quiet: bool = False,
) -> tuple[str, str | None, str | None, str | None, bool, bool]:
    """Resolve the CUDA wheel index for this host via ``kaine.wheel_index``.

    Mirrors ``scripts/install.sh``: probes the host and applies the binding
    decision table. If the resolver is missing or fails, the install never
    blocks: it falls back to the legacy ``NVIDIA_INDEX_URL``. An operator
    ``--index-url`` override is only honoured when the resolver succeeds; if
    the resolver fails, the override is dropped with a warning.

    When ``quiet`` is set, only warnings/errors are emitted (used by
    ``--print-index`` so stdout stays machine-readable).

    Returns ``(index_url, torch_pin, torchvision_pin, torchaudio_pin,
    selftest_required, torchaudio_unavailable)``.
    """
    resolver_args: list[str] = []
    if override is not None:
        resolver_args.extend(["--override", override])
    if research:
        resolver_args.append("--need-torchaudio")

    stdout, stderr, rc = _run_resolver(resolver_args, venv_python)
    data = _parse_resolver_result(stdout, stderr, rc)

    if data is None:
        if not quiet:
            print(
                "WARNING: CUDA wheel-index probe failed (kaine.wheel_index missing, "
                "exited non-zero, or produced unparseable output); using the legacy "
                f"hardcoded default index {NVIDIA_INDEX_URL}.",
                file=sys.stderr,
            )
            if override is not None:
                print(
                    "WARNING: the requested --index-url override could not be applied "
                    "because the resolver failed; continuing with the legacy default.",
                    file=sys.stderr,
                )
        return NVIDIA_INDEX_URL, None, None, None, False, False

    url = data.get("index_url")
    if not url:
        if not quiet:
            print(
                f"WARNING: CUDA wheel-index probe returned no index_url; using the legacy "
                f"hardcoded default index {NVIDIA_INDEX_URL}.",
                file=sys.stderr,
            )
            if override is not None:
                print(
                    "WARNING: the requested --index-url override could not be applied "
                    "because the resolver returned no index_url; continuing with the legacy default.",
                    file=sys.stderr,
                )
        return NVIDIA_INDEX_URL, None, None, None, False, False

    variant = data.get("variant")
    if variant == "cpu":
        print(
            "WARNING: no usable CUDA wheel index exists for this host; using the CPU index returned by the wheel-index resolver.",
            file=sys.stderr,
        )

    torch_pin, tv_pin, ta_pin, selftest = _extract_pins(data)
    ta_unavailable = bool(data.get("torchaudio_unavailable"))

    if not quiet:
        probes = data.get("probes") or {}
        for name in sorted(probes):
            value = probes[name]
            text = (
                json.dumps(value, sort_keys=True)
                if isinstance(value, (dict, list))
                else str(value)
            )
            print(f"wheel-index probe {name}: {text}")

        if variant == "cpu":
            print(
                "WARNING: CUDA flavor requested but no usable CUDA wheel index exists for this host; using the CPU index.",
                file=sys.stderr,
            )
            for warning in data.get("warnings") or []:
                print(f"WARNING: {warning}", file=sys.stderr)
        else:
            for warning in data.get("warnings") or []:
                print(f"wheel-index warning: {warning}")

        source = (
            "operator override (--index-url)"
            if override is not None
            else "host-resolved decision table (kaine.wheel_index)"
        )
        print(f"wheel index: {url} (source: {source})")
        if torch_pin:
            print(f"==> resolved torch {torch_pin} / torchvision {tv_pin} from {url}")
        print(json.dumps(data))

    return url, torch_pin, tv_pin, ta_pin, selftest, ta_unavailable


def _rocm_version_from_file(path: Path) -> str | None:
    """Return the first ``MAJOR.MINOR`` version found in ``path``."""
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    m = re.search(r"[0-9]+\.[0-9]+", text)
    return m.group(0) if m else None


def _auto_rocm_version() -> str | None:
    """Use ``KAINE_ROCM_VERSION`` or parse ``/opt/rocm/.info/version``."""
    env = os.environ.get("KAINE_ROCM_VERSION")
    if env:
        return env
    return _rocm_version_from_file(Path("/opt/rocm/.info/version"))


_ROCM_NAME_RE = re.compile(r"^\s*Name:\s*(\S+)", re.MULTILINE)


def _clean_gfx_token(raw: str) -> str | None:
    """Return the cleaned gfx name if ``raw`` names a real target.

    ``raw`` is the whitespace-delimited token (e.g. ``"gfx90a:xnack-"`` or
    ``"gfx11-generic"``).  Feature suffixes after the first ``:`` are
    discarded, then ``gfx000`` and names ending in ``-generic`` are dropped,
    and the remainder must match ``gfx[0-9a-f]+``.
    """
    token = raw.split(":", 1)[0]
    if token == "gfx000" or token.endswith("-generic"):
        return None
    if re.fullmatch(r"gfx[0-9a-f]+", token):
        return token
    return None


def _rocm_gfx_from_text(text: str) -> tuple[str, ...]:
    """Return order-stable unique gfx names extracted from ``rocminfo`` output.

    Only ``Name:`` tokens are parsed.  Feature suffixes (anything after the
    first ``:``), the reserved ``gfx000`` target, and ``-generic`` names are
    dropped.  Tokens that are not ``gfx[0-9a-f]+`` after cleaning are ignored.
    """
    seen: set[str] = set()
    out: list[str] = []
    for m in _ROCM_NAME_RE.finditer(text):
        val = _clean_gfx_token(m.group(1))
        if val is not None and val not in seen:
            seen.add(val)
            out.append(val)
    return tuple(out)


def _rocm_gfx_from_agent_text(text: str) -> tuple[str, ...]:
    """Return order-stable unique gfx names from ``rocm_agent_enumerator`` output.

    Each non-empty line is stripped and treated as a single token;
    feature suffixes after the first ``:`` are stripped, and
    ``gfx000`` / ``-generic`` targets are dropped.
    """
    seen: set[str] = set()
    out: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        val = _clean_gfx_token(line)
        if val is not None and val not in seen:
            seen.add(val)
            out.append(val)
    return tuple(out)


def _rocm_gfx_from_command(cmd: list[str]) -> tuple[str, ...] | None:
    """Run ``cmd`` and extract unique gfx names from its stdout.

    Output is parsed even when the command exits non-zero, matching the bash
    installer's behaviour of keeping names from a failing ``rocminfo``.
    """
    exe = shutil.which(cmd[0])
    if not exe:
        return None
    try:
        proc = subprocess.run(
            [exe, *cmd[1:]],
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    output = proc.stdout or ""
    gfx = _rocm_gfx_from_text(output)
    if gfx:
        return gfx
    gfx = _rocm_gfx_from_agent_text(output)
    return gfx if gfx else None


def _auto_rocm_gfx() -> tuple[str | None, str]:
    """Use ``KAINE_ROCM_GFX`` or detect from ``rocminfo`` / ``rocm_agent_enumerator``.

    Returns ``(gfx_targets, source)`` where ``source`` identifies how the
    targets were obtained: ``KAINE_ROCM_GFX``, ``rocminfo``,
    ``rocm_agent_enumerator``, or ``none``.
    """
    env = os.environ.get("KAINE_ROCM_GFX")
    if env:
        return env, "KAINE_ROCM_GFX"
    gfx = _rocm_gfx_from_command(["rocminfo"])
    if gfx:
        return ",".join(gfx), "rocminfo"
    gfx = _rocm_gfx_from_command(["rocm_agent_enumerator"])
    if gfx:
        return ",".join(gfx), "rocm_agent_enumerator"
    return None, "none"


def _resolve_rocm_index(
    venv_python: Path | None = None,
    quiet: bool = False,
    research: bool = False,
) -> tuple[str, str | None, str | None, str | None, bool, bool]:
    """Resolve the ROCm wheel index for this host via ``kaine.wheel_index``.

    Unlike CUDA, ROCm never falls back to a hardcoded index: if the version
    cannot be determined or the resolver returns no wheel, the installer exits
    with a clear error and prints any resolver warnings to stderr.
    """
    rocm_version = _auto_rocm_version()
    if rocm_version is None:
        print(
            "install.py: could not determine ROCm version. "
            "Set KAINE_ROCM_VERSION (e.g. 7.2) and re-run.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    gfx, gfx_source = _auto_rocm_gfx()
    resolver_args = ["--rocm-version", rocm_version]
    if gfx:
        resolver_args.extend(["--gfx", gfx])
    if research:
        resolver_args.append("--need-torchaudio")

    stdout, stderr, rc = _run_resolver(resolver_args, venv_python)
    data = _parse_resolver_result(stdout, stderr, rc)
    url = data.get("index_url") if data else None

    if not url:
        gfx_display = gfx if gfx else "auto-detected"
        print(
            "install.py: no ROCm wheel index carries a torch in the project's "
            f"tested range for ROCm {rocm_version} (gfx: {gfx_display}).",
            file=sys.stderr,
        )
        if data:
            for warning in data.get("warnings") or []:
                print(f"WARNING: {warning}", file=sys.stderr)
        raise SystemExit(1)

    torch_pin, tv_pin, ta_pin, selftest = _extract_pins(data)
    ta_unavailable = bool(data.get("torchaudio_unavailable"))
    if not quiet:
        gfx_display = gfx if gfx is not None else "none detected"
        print(
            f"==> ROCm version: {rocm_version}; "
            f"gfx targets: {gfx_display} (source: {gfx_source})"
        )
        for warning in data.get("warnings") or []:
            print(f"wheel-index warning: {warning}")
        print(f"wheel index: {url} (source: host-resolved ROCm decision table)")
        if torch_pin:
            print(f"==> resolved torch {torch_pin} / torchvision {tv_pin} from {url}")

    return url, torch_pin, tv_pin, ta_pin, selftest, ta_unavailable


def torch_index_url(
    flavor: str,
    override: str | None = None,
    research: bool = False,
) -> str | None:
    """Return the pip ``--index-url`` for ``flavor`` (``None`` for MPS/PyPI).

    Single source of truth for the accelerator→wheel-index mapping. The
    container image build reuses this verbatim (``install.py --print-index
    <flavor>``) instead of re-deriving the URLs, so the Dockerfile and the
    host installer cannot drift.

    ``cuda`` and ``rocm`` are host-resolved by ``kaine.wheel_index``; the
    remaining flavors use fixed URLs. The ``--index-url`` operator override
    applies only to ``cuda`` and is ignored for all other flavors (with a
    notice on stderr).
    """
    if flavor not in VALID_FLAVORS:
        raise KeyError(flavor)
    if override is None:
        override = _argv_index_override()
    if flavor == "cuda":
        url, *_ = _resolve_cuda_index(research, override, quiet=True)
        return url
    if override is not None:
        print(
            f"NOTICE: ignoring --index-url for flavor '{flavor}' (only the cuda "
            f"flavor accepts an operator index override).",
            file=sys.stderr,
        )
    if flavor == "rocm":
        url, *_ = _resolve_rocm_index(quiet=True)
        return url
    return _INDEX_BY_FLAVOR[flavor]


def run(cmd: list[str], **kwargs) -> None:
    print("==>", " ".join(cmd))
    subprocess.check_call(cmd, **kwargs)


def detect_flavor(force: str | None) -> str:
    if force in VALID_FLAVORS:
        return force
    if force is not None:
        sys.exit(f"unknown flavor {force!r}")

    # NVIDIA GPU
    if shutil.which("nvidia-smi") is not None:
        try:
            subprocess.check_call(
                ["nvidia-smi", "-L"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            print("==> nvidia-smi present: picking CUDA wheels")
            return "cuda"
        except subprocess.CalledProcessError:
            pass

    # AMD ROCm
    if shutil.which("rocm-smi") is not None or Path("/opt/rocm").is_dir():
        print("==> ROCm detected: picking ROCm wheels")
        return "rocm"

    # Intel XPU
    if shutil.which("xpu-smi") is not None or shutil.which("sycl-ls") is not None:
        print("==> Intel XPU detected: picking XPU wheels")
        return "xpu"

    # Apple Silicon MPS
    import platform as _platform
    if _platform.system() == "Darwin" and _platform.machine() == "arm64":
        print("==> macOS arm64 detected: picking MPS (default PyPI) wheels")
        return "mps"

    print("==> no accelerator detected: picking CPU wheels")
    return "cpu"


_FLAVOR_PROBE = """\
import sys
try:
    import torch
except ImportError:
    print("absent"); sys.exit(0)
ver = getattr(torch, "version", None)
if ver is not None:
    if getattr(ver, "hip", None) is not None:
        print("rocm"); sys.exit(0)
    if getattr(ver, "cuda", None) is not None:
        print("cuda"); sys.exit(0)
    if getattr(ver, "xpu", None) is not None:
        print("xpu"); sys.exit(0)
xpu_mod = getattr(torch, "xpu", None)
if xpu_mod is not None and hasattr(xpu_mod, "_is_compiled") and xpu_mod._is_compiled():
    print("xpu"); sys.exit(0)
import platform
if platform.system() == "Darwin" and platform.machine() == "arm64":
    try:
        if torch.backends.mps.is_built():
            print("mps"); sys.exit(0)
    except Exception:
        pass
print("cpu")
"""


def torch_installed_flavor(py: Path) -> str:
    try:
        out = subprocess.check_output(
            [str(py), "-c", _FLAVOR_PROBE],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except subprocess.CalledProcessError:
        return "absent"
    return out or "absent"


def _install_torchaudio(
    pip: Path,
    index_url: str | None,
    ta_pin: str | None,
    constraints: Path,
    *,
    research: bool = False,
    force_reinstall: bool = False,
) -> None:
    """Install torchaudio the same way for --research and for coherence.

    The pip command is identical in both modes; only the operator-facing
    message changes.
    """
    label = "[--research] " if research else ""
    extra = "" if research else " (audio-stack coherence)"
    cmd = [str(pip), "install"]
    if force_reinstall:
        cmd.append("--force-reinstall")
    if ta_pin is not None and index_url is not None:
        print(f"==> {label}installing torchaudio=={ta_pin} from {index_url}{extra}")
        cmd.extend(
            ["--index-url", index_url, "-c", str(constraints), f"torchaudio=={ta_pin}"]
        )
    elif index_url is None:
        print(
            f"==> {label}installing torchaudio (default PyPI wheel for MPS){extra}"
        )
        cmd.extend(["-c", str(constraints), "torchaudio"])
    else:
        print(f"==> {label}installing torchaudio from {index_url}{extra}")
        cmd.extend(["--index-url", index_url, "-c", str(constraints), "torchaudio"])
    run(cmd)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--cpu", dest="force", action="store_const", const="cpu")
    group.add_argument("--cuda", dest="force", action="store_const", const="cuda")
    group.add_argument("--rocm", dest="force", action="store_const", const="rocm")
    group.add_argument("--xpu", dest="force", action="store_const", const="xpu")
    group.add_argument("--mps", dest="force", action="store_const", const="mps")
    parser.add_argument(
        "--print-index",
        metavar="FLAVOR",
        choices=sorted(VALID_FLAVORS),
        help=(
            "print the pip --index-url for FLAVOR "
            "(cuda|rocm|xpu|cpu|mps) and exit; prints an empty line for mps "
            "(default PyPI). Used by the container image build to reuse this "
            "mapping instead of re-deriving it."
        ),
    )
    parser.add_argument(
        "--print-torch-spec",
        action="store_true",
        help="print the resolved torch requirement spec and exit",
    )
    parser.add_argument(
        "--index-url",
        default=None,
        metavar="URL",
        help="override the resolved CUDA wheel index (ignored for other flavors)",
    )
    parser.add_argument("--python", default="python3", help="interpreter for the venv")
    parser.add_argument(
        "--no-wizard",
        action="store_true",
        help="do not offer to run the first-run setup wizard after install",
    )
    parser.add_argument(
        "--research",
        action="store_true",
        help=(
            "ALSO install the perception extras (.[perception] = audio+vision "
            "incl. PyAV) for reproducible-feed research runs; the default install "
            "stays lean (no cv2/av/funasr)"
        ),
    )
    parser.add_argument(
        "--retry-gpu",
        action="store_true",
        help=(
            "delete the GPU self-test fallback marker and retry the "
            "host-resolved CUDA index (only useful with the CUDA flavor)"
        ),
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    os.chdir(repo_root)

    # Accessor mode: emit the wheel index / torch spec and exit before any
    # venv work, so the image build can shell out for a single source of truth.
    if args.print_torch_spec:
        print(torch_spec(repo_root))
        return
    if args.print_index is not None:
        index_url = torch_index_url(args.print_index)
        print(index_url if index_url is not None else "")
        return

    venv_dir = Path(os.environ.get("KAINE_VENV_DIR", ".venv"))
    if not venv_dir.is_absolute():
        venv_dir = repo_root / venv_dir
    venv = venv_dir.resolve()

    if not venv.exists():
        print(f"==> creating venv at {venv}/ using {args.python}")
        run([args.python, "-m", "venv", str(venv)])

    pip = venv / "bin" / "pip"
    py = venv / "bin" / "python"
    marker_path = _accel_fallback_marker_path(venv)

    if args.retry_gpu and marker_path.exists():
        print("==> --retry-gpu: clearing previous GPU fallback marker")
        marker_path.unlink()

    run([str(pip), "install", "--quiet", "--upgrade", "pip"])

    flavor = detect_flavor(args.force)

    # Audio-stack coherence: if torchaudio is already installed and this is
    # not a --research run, keep the audio stack coherent on every flavor.
    installed_ta = _installed_package_version(py, "torchaudio")
    need_torchaudio_coherent = not args.research and installed_ta is not None
    if need_torchaudio_coherent:
        print(
            "==> torchaudio is installed; keeping the audio stack coherent "
            "(resolving with --need-torchaudio)"
        )

    gpu_index_url: str | None = None
    resolve_research = args.research or need_torchaudio_coherent
    ta_unavailable = False

    if flavor == "cuda":
        (
            gpu_index_url,
            torch_pin,
            tv_pin,
            ta_pin,
            selftest,
            ta_unavailable,
        ) = _resolve_cuda_index(
            resolve_research, override=args.index_url, venv_python=py
        )
        index_url = gpu_index_url
        marker = _read_accel_fallback_marker(marker_path)
        installed_base = _installed_torch_base(py)
        if _marker_matches(
            marker,
            index_url=gpu_index_url,
            torch_pin=torch_pin,
            installed_base=installed_base,
        ):
            print(
                f"NOTICE: GPU self-test previously failed for this index/torch version; "
                f"recorded in {marker_path}. Using CPU wheels. Use --retry-gpu to "
                "attempt the GPU index again.",
                file=sys.stderr,
            )
            index_url = CPU_INDEX_URL
            selftest = False
    elif flavor == "rocm":
        if args.index_url is not None:
            print(
                f"NOTICE: ignoring --index-url for flavor '{flavor}' (only the cuda "
                f"flavor accepts an operator index override).",
                file=sys.stderr,
            )
        (
            index_url,
            torch_pin,
            tv_pin,
            ta_pin,
            selftest,
            ta_unavailable,
        ) = _resolve_rocm_index(venv_python=py, research=resolve_research)
    else:
        index_url = torch_index_url(flavor, override=args.index_url)
        torch_pin = tv_pin = ta_pin = None
        selftest = False

    torch_spec_value = torch_spec(repo_root)

    # The effective target flavor is the flavor of the index that will actually
    # be installed from.  When the resolver or a GPU self-test fallback marker
    # routes a cuda request to the CPU index, the target flavor becomes cpu.
    effective_target_flavor = flavor
    if index_url == CPU_INDEX_URL:
        effective_target_flavor = "cpu"

    # Refusals for indices that cannot satisfy the torchaudio requirement.
    if args.research and ta_unavailable:
        print(
            f"install: --research needs torchaudio, but {index_url} publishes no "
            f"torchaudio for torch {torch_pin}; choose a different --index-url or drop --research",
            file=sys.stderr,
        )
        raise SystemExit(1)
    if need_torchaudio_coherent and ta_unavailable:
        print(
            f"install: torchaudio is installed, but {index_url} publishes no "
            f"torchaudio for torch {torch_pin}; choose a different --index-url, or "
            "uninstall torchaudio first to drop the audio stack",
            file=sys.stderr,
        )
        raise SystemExit(1)

    # Idempotent torch install: only skip when a torch-2.x with the right
    # flavor and, when pinned, the right base version is already present.
    # Also force-reinstall when the installed local build tag differs from
    # the target index tag, because pip treats "2.14.0+cpu" as satisfying
    # "torch==2.14.0" and will not swap flavors without --force-reinstall.
    need_install = True
    force_reinstall = False
    installed_base = _installed_torch_base(py)
    try:
        subprocess.check_call(
            [
                str(py),
                "-c",
                "import torch, sys; sys.exit(0 if torch.__version__.startswith('2.') else 1)",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        pass
    else:
        installed_flavor = torch_installed_flavor(py)
        if installed_flavor == effective_target_flavor:
            if torch_pin is not None and installed_base != torch_pin:
                print(
                    f"==> torch installed with base version {installed_base} but want "
                    f"{torch_pin}; reinstalling"
                )
            else:
                print(
                    f"==> torch already installed at the right flavor ({installed_flavor}); "
                    "skipping torch install"
                )
                need_install = False
        else:
            print(
                f"==> torch installed with flavor {installed_flavor!r} but want "
                f"{effective_target_flavor!r}; reinstalling"
            )
            force_reinstall = True
            need_install = True

        target_tag = _index_tag(index_url)
        installed_tag = _installed_torch_tag(py)
        if _needs_force_reinstall(installed_tag, target_tag, index_url):
            print(
                f"==> installed torch build tag '{installed_tag}' differs from "
                f"target index tag '{target_tag}'; forcing reinstall"
            )
            force_reinstall = True
            need_install = True

    if need_install:
        install_cmd = [str(pip), "install"]
        if force_reinstall:
            install_cmd.append("--force-reinstall")
        if torch_pin is not None:
            if tv_pin is not None:
                print(
                    f"==> installing torch=={torch_pin} torchvision=={tv_pin} from {index_url}"
                )
                run(
                    [
                        *install_cmd,
                        "--index-url",
                        index_url,
                        f"torch=={torch_pin}",
                        f"torchvision=={tv_pin}",
                    ]
                )
            else:
                print(
                    f"==> installing torch=={torch_pin} torchvision from {index_url}"
                )
                run(
                    [
                        *install_cmd,
                        "--index-url",
                        index_url,
                        f"torch=={torch_pin}",
                        "torchvision",
                    ]
                )
        elif index_url is None:
            print(
                f"==> installing {torch_spec_value} torchvision "
                "(default PyPI wheel for MPS)"
            )
            run([*install_cmd, torch_spec_value, "torchvision"])
        else:
            print(
                f"==> installing {torch_spec_value} torchvision from {index_url}"
            )
            run(
                [
                    *install_cmd,
                    "--index-url",
                    index_url,
                    torch_spec_value,
                    "torchvision",
                ]
            )

    # GPU numerical self-test for host-resolved unified-memory wheels.
    if selftest:
        print("==> running GPU numerical self-test")
        try:
            subprocess.check_call([str(py), "-m", "kaine.accel_selftest"])
        except subprocess.CalledProcessError as exc:
            if exc.returncode == 1:
                reason = "GPU numerical self-test failed"
                print(
                    "WARNING: the GPU wheels failed the numerical self-test on this "
                    "unified-memory device; CPU wheels will be installed instead.",
                    file=sys.stderr,
                )
            else:
                reason = f"GPU numerical self-test could not run (exit {exc.returncode})"
                print(
                    f"WARNING: the GPU numerical self-test could not run "
                    f"(exit {exc.returncode}); CPU wheels will be installed instead.",
                    file=sys.stderr,
                )
            cpu_install_cmd = [str(pip), "install", "--force-reinstall", "--index-url", CPU_INDEX_URL]
            if tv_pin is not None:
                run(
                    [
                        *cpu_install_cmd,
                        f"torch=={torch_pin}",
                        f"torchvision=={tv_pin}",
                    ]
                )
            else:
                run(
                    [
                        *cpu_install_cmd,
                        f"torch=={torch_pin}",
                        "torchvision",
                    ]
                )
            index_url = CPU_INDEX_URL
            if gpu_index_url is not None:
                _write_accel_fallback_marker(
                    marker_path,
                    reason=reason,
                    index_url=gpu_index_url,
                    torch=torch_pin or installed_base or "",
                )
        else:
            print("==> GPU numerical self-test passed")

    # Ensure the constraints file never pins a stale torchaudio.
    try:
        installed_ta = subprocess.check_output(
            [
                str(py),
                "-c",
                "import importlib.metadata as md; print(md.version('torchaudio'))",
            ],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except subprocess.CalledProcessError:
        installed_ta = ""
    if _torchaudio_should_uninstall(installed_ta, ta_pin, index_url):
        print(
            f"==> uninstalling stale torchaudio {installed_ta} "
            f"(target pin: {ta_pin or 'none'})"
        )
        run([str(pip), "uninstall", "-y", "torchaudio"])

    constraints = venv / "kaine-torch-constraints.txt"
    pinned = write_torch_constraints(py, constraints)
    print(f"==> pinned torch stack: {pinned}")

    run(
        [
            str(pip),
            "install",
            "--quiet",
            "-c",
            str(constraints),
            "-e",
            ".[test]",
        ]
    )

    # Audio-stack coherence for a pre-existing torchaudio on any flavor:
    # make the installed torchaudio follow the selected torch stack even when
    # --research was not requested.
    if need_torchaudio_coherent:
        _install_torchaudio(
            pip, index_url, ta_pin, constraints, research=False, force_reinstall=force_reinstall
        )
        pinned = write_torch_constraints(py, constraints)
        print(f"==> pinned torch stack: {pinned}")

    # --research: ALSO provision the perception extras (audio+vision incl. PyAV)
    # so the reproducible perception feed can decode playlist media (cv2 video +
    # av audio) on a fresh research machine. The default install stays lean.
    if args.research:
        _install_torchaudio(
            pip, index_url, ta_pin, constraints, research=True, force_reinstall=force_reinstall
        )
        pinned = write_torch_constraints(py, constraints)
        print(f"==> pinned torch stack: {pinned}")
        print(
            f"==> [--research] installing perception extras: "
            f"pip install -c {constraints} -e .[perception]"
        )
        print(
            "    (audio: sounddevice, webrtcvad, funasr, librosa, av;  "
            "vision: opencv-python-headless)"
        )
        run([str(pip), "install", "-c", str(constraints), "-e", ".[perception]"])
        print(
            "==> [--research] perception extras installed "
            "(playlist audio/video decode ready)"
        )

    print("==> verifying")
    run(
        [
            str(py),
            "-c",
            "import torch, json; from kaine.hardware import describe_host; "
            + "print('torch', torch.__version__); "
            + "print('cuda.is_available', torch.cuda.is_available()); "
            + "print(json.dumps(describe_host(), indent=2, default=str))",
        ]
    )
    run(
        [
            str(py),
            "-c",
            "import sys; from kaine.torch_stack import check_torch_stack; "
            "problems = check_torch_stack(); "
            "[print('TORCH STACK MISMATCH:', p, file=sys.stderr) for p in problems]; "
            "sys.exit(1 if problems else 0)",
        ]
    )
    print("==> install complete")

    # GPU trainer note: this script sets up the KAINE runtime venv only. The
    # voice-alignment GPU trainer (Unsloth Studio on NVIDIA, unsloth-core on AMD)
    # is a SEPARATE environment — never install it into the KAINE runtime venv.
    # For Qwen3.5 support the trainer env also requires transformers v5 (Unsloth
    # Studio ships 4.x by default). See docs/hardware.md#qwen35-trainer-prerequisites
    # for the upgrade command and the mainline-GGUF conversion requirement.

    # First-run wizard hand-off. Offer it only interactively (a TTY) and when
    # not suppressed. It writes config/kaine.operator.toml and never boots.
    if not args.no_wizard and sys.stdin.isatty() and sys.stdout.isatty():
        ans = input("Run the first-run setup wizard now? [y/N] ").strip().lower()
        if ans in ("y", "yes"):
            run([str(py), "-m", "kaine.setup"])
        else:
            print(
                f"==> skipped. Run it later with: {venv}/bin/python -m kaine.setup"
            )
    else:
        print(
            f"==> run the first-run wizard with: {venv}/bin/python -m kaine.setup"
        )


if __name__ == "__main__":
    main()
