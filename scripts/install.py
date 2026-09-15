#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Python port of scripts/install.sh.

Use on hosts where Bash is not the canonical shell (macOS with zsh-only
operators, BSD variants). Behavior matches scripts/install.sh.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Legacy hardcoded CUDA wheel index. Kept only as the documented
# fallback for when the host-aware resolver (kaine.wheel_index) is
# unavailable or fails; normal CUDA installs resolve per host instead.
NVIDIA_INDEX_URL = "https://download.pytorch.org/whl/cu128"
ROCM_INDEX_URL = "https://download.pytorch.org/whl/rocm6.2"
XPU_INDEX_URL = "https://download.pytorch.org/whl/xpu"
CPU_INDEX_URL = "https://download.pytorch.org/whl/cpu"
TORCH_SPEC = "torch>=2.5,<3"

# MPS uses the default PyPI wheel — no --index-url needed.
_INDEX_BY_FLAVOR: dict[str, str | None] = {
    "cuda": NVIDIA_INDEX_URL,
    "rocm": ROCM_INDEX_URL,
    "xpu": XPU_INDEX_URL,
    "cpu": CPU_INDEX_URL,
    "mps": None,
}


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


def _resolve_cuda_index(override: str | None) -> str:
    """Resolve the CUDA wheel index for this host via ``kaine.wheel_index``.

    Mirrors ``scripts/install.sh``: probes the CPU architecture, the driver's
    CUDA version, every NVIDIA device's compute capability and the
    unified-memory classification, then applies the binding decision table
    and fallback ladder. The import is lazy and guarded: if the resolver is
    missing or fails, we degrade to the legacy ``NVIDIA_INDEX_URL`` so the
    installer is never blocked.
    """
    try:
        from kaine.wheel_index import collect_probes, resolve_index

        result = resolve_index(collect_probes(), override=override)
        index_url = result["index_url"]
    except Exception as exc:  # resolver unavailable or failed: never block
        print(
            "warning: host-aware CUDA wheel-index resolver unavailable "
            f"({exc!r}); falling back to legacy {NVIDIA_INDEX_URL}",
            file=sys.stderr,
        )
        if override is not None:
            print(
                "warning: resolver failed; honouring operator override "
                f"--index-url {override}",
                file=sys.stderr,
            )
            return override
        return NVIDIA_INDEX_URL
    _report_cuda_resolution(result, override)
    return index_url


def _report_cuda_resolution(result: dict, override: str | None) -> None:
    """Print probe values, resolved URL, table-vs-override source, warnings.

    The report goes to stdout for normal installer runs; when the output is
    consumed programmatically (``--print-index``, used by the container image
    build) it is diverted to stderr so stdout stays machine-readable.
    Resolver warnings always go to stderr.
    """
    stream = sys.stderr if "--print-index" in sys.argv[1:] else sys.stdout
    variant = str(result.get("variant") or "")
    if override is not None or "override" in variant.lower():
        source = "operator override (--index-url)"
    else:
        source = "host-resolved decision table"
    if variant:
        source = f"{source} [variant: {variant}]"
    print("CUDA wheel index resolution:", file=stream)
    print(f"  index_url: {result.get('index_url')}", file=stream)
    print(f"  source: {source}", file=stream)
    probes = result.get("probes")
    if isinstance(probes, dict):
        for name in sorted(probes):
            print(f"  probe {name}: {probes[name]}", file=stream)
    else:
        print(f"  probes: {probes}", file=stream)
    reason = result.get("selected_reason")
    if reason:
        print(f"  selected_reason: {reason}", file=stream)
    for entry in result.get("rejected") or []:
        if isinstance(entry, dict):
            print(
                f"  rejected {entry.get('index')}: {entry.get('reason')}",
                file=sys.stderr,
            )
        else:
            print(f"  rejected: {entry}", file=sys.stderr)
    for warning in result.get("warnings") or []:
        print(f"warning: wheel_index: {warning}", file=sys.stderr)


def torch_index_url(flavor: str, override: str | None = None) -> str | None:
    """Return the pip ``--index-url`` for ``flavor`` (``None`` for MPS/PyPI).

    Single source of truth for the accelerator→wheel-index mapping. The
    container image build reuses this verbatim (`install.py --print-index
    <flavor>`) instead of re-deriving the CUDA/ROCm/XPU/CPU index URLs, so the
    Dockerfile and the host installer can never drift.

    For ``cuda`` the URL is host-resolved by ``kaine.wheel_index``: it
    probes the CPU architecture, the driver's CUDA version, every NVIDIA
    device's compute capability and the unified-memory classification, then
    applies the binding decision table and fallback ladder (mirroring
    ``scripts/install.sh``). ``override`` -- the ``--index-url`` CLI flag --
    replaces the resolved URL for the cuda flavor only; with any other
    flavor it is ignored with a notice on stderr. When no explicit
    ``override`` is passed, the command line is pre-scanned for
    ``--index-url`` so every call site (installer, wizard, ``--print-index``)
    honours the flag. If the resolver cannot be imported or fails, we fall
    back to the legacy ``NVIDIA_INDEX_URL`` with a warning on stderr; the
    installer is never blocked.
    """
    if flavor not in _INDEX_BY_FLAVOR:
        raise KeyError(flavor)
    if override is None:
        override = _argv_index_override()
    if flavor != "cuda":
        if override is not None:
            print(
                f"notice: --index-url {override} applies only to the cuda "
                f"flavor; ignored for {flavor!r}, proceeding unchanged",
                file=sys.stderr,
            )
        return _INDEX_BY_FLAVOR[flavor]
    return _resolve_cuda_index(override)


def run(cmd: list[str], **kwargs) -> None:
    print("==>", " ".join(cmd))
    subprocess.check_call(cmd, **kwargs)


def detect_flavor(force: str | None) -> str:
    valid = set(_INDEX_BY_FLAVOR)
    if force in valid:
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
try:
    hip = getattr(getattr(torch, "version", None), "hip", None)
    if hip is not None:
        print("rocm"); sys.exit(0)
except Exception:
    pass
try:
    if torch.cuda.is_available():
        print("cuda"); sys.exit(0)
except Exception:
    pass
try:
    xpu = getattr(torch, "xpu", None)
    if xpu is not None and xpu.is_available():
        print("xpu"); sys.exit(0)
except Exception:
    pass
try:
    if torch.backends.mps.is_available():
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--cpu",  dest="force", action="store_const", const="cpu")
    group.add_argument("--cuda", dest="force", action="store_const", const="cuda")
    group.add_argument("--rocm", dest="force", action="store_const", const="rocm")
    group.add_argument("--xpu",  dest="force", action="store_const", const="xpu")
    group.add_argument("--mps",  dest="force", action="store_const", const="mps")
    parser.add_argument(
        "--print-index",
        metavar="FLAVOR",
        choices=sorted(_INDEX_BY_FLAVOR),
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
        help="print the pinned torch requirement spec and exit",
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
    args = parser.parse_args()

    # Accessor mode: emit the wheel index / torch spec and exit before any
    # venv work, so the image build can shell out for a single source of truth.
    if args.print_torch_spec:
        print(TORCH_SPEC)
        return
    if args.print_index is not None:
        index_url = torch_index_url(args.print_index)
        print(index_url if index_url is not None else "")
        return

    repo_root = Path(__file__).resolve().parent.parent
    os.chdir(repo_root)
    venv = repo_root / ".venv"
    if not venv.exists():
        print(f"==> creating venv at {venv} using {args.python}")
        run([args.python, "-m", "venv", str(venv)])

    pip = venv / "bin" / "pip"
    py = venv / "bin" / "python"

    run([str(pip), "install", "--quiet", "--upgrade", "pip"])

    flavor = detect_flavor(args.force)
    index_url = _INDEX_BY_FLAVOR[flavor]

    current = torch_installed_flavor(py)
    if current == flavor:
        print(f"==> torch already installed at {flavor}; skipping torch install")
    else:
        if current != "absent":
            print(f"==> reinstalling torch: have {current!r}, want {flavor!r}")
        if index_url is None:
            # MPS: macOS arm64 ships MPS in the default PyPI wheel.
            run([str(pip), "install", TORCH_SPEC])
        else:
            run([str(pip), "install", "--index-url", index_url, TORCH_SPEC])

    run([str(pip), "install", "--quiet", "-e", ".[test]"])

    # --research: ALSO provision the perception extras (audio+vision incl. PyAV)
    # so the reproducible perception feed can decode playlist media (cv2 video +
    # av audio) on a fresh research machine. The default install stays lean.
    if args.research:
        print("==> [--research] installing perception extras: pip install -e .[perception]")
        print(
            "    (audio: sounddevice, webrtcvad, funasr, librosa, av;  "
            "vision: opencv-python-headless)"
        )
        run([str(pip), "install", "-e", ".[perception]"])
        print("==> [--research] perception extras installed (playlist audio/video decode ready)")

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
    print("==> install complete")

    # GPU trainer note: this script sets up the KAINE runtime venv only. The
    # voice-alignment GPU trainer (Unsloth Studio on NVIDIA, unsloth-core on AMD)
    # is a SEPARATE environment — never install it into .venv/. For Qwen3.5
    # support the trainer env also requires transformers v5 (Unsloth Studio ships
    # 4.x by default). See docs/hardware.md#qwen35-trainer-prerequisites for the
    # upgrade command and the mainline-GGUF conversion requirement.

    # First-run wizard hand-off. Offer it only interactively (a TTY) and when
    # not suppressed. It writes config/kaine.operator.toml and never boots.
    if not args.no_wizard and sys.stdin.isatty() and sys.stdout.isatty():
        ans = input("Run the first-run setup wizard now? [y/N] ").strip().lower()
        if ans in ("y", "yes"):
            run([str(py), "-m", "kaine.setup"])
        else:
            print("==> skipped. Run it later with: .venv/bin/python -m kaine.setup")
    else:
        print("==> run the first-run wizard with: .venv/bin/python -m kaine.setup")


if __name__ == "__main__":
    main()
