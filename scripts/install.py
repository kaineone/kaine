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
            "print('torch', torch.__version__); "
            "print('cuda.is_available', torch.cuda.is_available()); "
            "print(json.dumps(describe_host(), indent=2, default=str))",
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
