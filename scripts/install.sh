#!/usr/bin/env bash
# KAINE installer: detects host hardware and installs PyTorch from the
# matching wheel index, then installs the rest of KAINE editable.
#
# Idempotent — safe to re-run. Run from the repo root.
#
#   bash scripts/install.sh           # auto-detect
#   bash scripts/install.sh --cpu     # force CPU wheels
#   bash scripts/install.sh --cuda    # force CUDA wheels (cu128)
#   bash scripts/install.sh --rocm    # force ROCm wheels (rocm6.2)
#   bash scripts/install.sh --xpu     # force Intel XPU wheels
#   bash scripts/install.sh --mps     # force macOS MPS (default PyPI wheel)
#   bash scripts/install.sh --research # ALSO install the perception extras
#                                       # (.[perception] = audio+vision incl.
#                                       # PyAV) for reproducible-feed research runs
#
# The default install stays lean (no cv2/av/funasr). The venv is created at
# .venv/ if absent. Use --python /path/to/python to override the interpreter the
# venv is built from.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
ROOT="$(pwd)"

PYTHON_BIN="python3"
FORCE=""
NO_WIZARD=0
RESEARCH=0
TORCH_SPEC="torch>=2.5,<3"
NVIDIA_INDEX_URL="https://download.pytorch.org/whl/cu128"
ROCM_INDEX_URL="https://download.pytorch.org/whl/rocm6.2"
XPU_INDEX_URL="https://download.pytorch.org/whl/xpu"
CPU_INDEX_URL="https://download.pytorch.org/whl/cpu"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cpu)  FORCE="cpu";  shift ;;
    --cuda) FORCE="cuda"; shift ;;
    --rocm) FORCE="rocm"; shift ;;
    --xpu)  FORCE="xpu";  shift ;;
    --mps)  FORCE="mps";  shift ;;
    --python) PYTHON_BIN="$2"; shift 2 ;;
    --no-wizard) NO_WIZARD=1; shift ;;
    --research) RESEARCH=1; shift ;;
    --help|-h)
      sed -n '2,17p' "$0"; exit 0 ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
done

if [[ ! -d ".venv" ]]; then
  echo "==> creating venv at .venv/ using $PYTHON_BIN"
  "$PYTHON_BIN" -m venv .venv
fi

PIP=".venv/bin/pip"
PY=".venv/bin/python"

echo "==> upgrading pip"
"$PIP" install --quiet --upgrade pip

# Determine wheel flavor.
flavor=""
if [[ -n "$FORCE" ]]; then
  flavor="$FORCE"
  echo "==> wheel flavor forced via flag: $flavor"
elif command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
  flavor="cuda"
  echo "==> nvidia-smi present: picking CUDA wheels"
elif command -v rocm-smi >/dev/null 2>&1 || [ -d /opt/rocm ]; then
  flavor="rocm"
  echo "==> ROCm detected: picking ROCm wheels"
elif command -v xpu-smi >/dev/null 2>&1 || command -v sycl-ls >/dev/null 2>&1; then
  flavor="xpu"
  echo "==> Intel XPU detected: picking XPU wheels"
elif [ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ]; then
  flavor="mps"
  echo "==> macOS arm64 detected: picking MPS (default PyPI) wheels"
else
  flavor="cpu"
  echo "==> no accelerator detected: picking CPU wheels"
fi

case "$flavor" in
  cuda) INDEX_URL="$NVIDIA_INDEX_URL" ;;
  rocm) INDEX_URL="$ROCM_INDEX_URL" ;;
  xpu)  INDEX_URL="$XPU_INDEX_URL" ;;
  cpu)  INDEX_URL="$CPU_INDEX_URL" ;;
  mps)  INDEX_URL="" ;;  # macOS MPS ships in the default PyPI wheel
  *) echo "unknown flavor $flavor" >&2; exit 3 ;;
esac

# Idempotent torch install: probe which flavor is currently installed.
_FLAVOR_PROBE='
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
'

need_install=1
if "$PY" -c "import torch; import sys; sys.exit(0 if torch.__version__.startswith('2.') else 1)" 2>/dev/null; then
  installed_flavor=$("$PY" -c "$_FLAVOR_PROBE" 2>/dev/null || echo "unknown")
  if [[ "$installed_flavor" == "$flavor" ]]; then
    echo "==> torch already installed at the right flavor ($installed_flavor); skipping torch install"
    need_install=0
  else
    echo "==> torch installed with flavor '$installed_flavor' but want '$flavor'; reinstalling"
  fi
fi

if [[ "$need_install" -eq 1 ]]; then
  if [[ "$flavor" == "mps" ]]; then
    echo "==> installing $TORCH_SPEC (default PyPI wheel for MPS)"
    "$PIP" install "$TORCH_SPEC"
  else
    echo "==> installing $TORCH_SPEC from $INDEX_URL"
    "$PIP" install --index-url "$INDEX_URL" "$TORCH_SPEC"
  fi
fi

echo "==> installing the rest of KAINE (editable, with test deps)"
"$PIP" install --quiet -e ".[test]"

# --research: ALSO provision the perception extras (audio+vision incl. PyAV) so
# the reproducible perception feed can decode playlist media (cv2 video + av
# audio) on a fresh research machine. The default install stays lean.
if [[ "$RESEARCH" -eq 1 ]]; then
  echo "==> [--research] installing perception extras: pip install -e .[perception]"
  echo "    (audio: sounddevice, webrtcvad, funasr, librosa, av;  vision: opencv-python-headless)"
  "$PIP" install -e ".[perception]"
  echo "==> [--research] perception extras installed (playlist audio/video decode ready)"
fi

echo "==> verifying"
"$PY" - <<'PY'
import torch
from kaine.hardware import describe_host
import json
print("torch", torch.__version__)
print("cuda.is_available", torch.cuda.is_available())
print(json.dumps(describe_host(), indent=2, default=str))
PY

echo "==> install complete"

# GPU trainer note: this script sets up the KAINE runtime venv only. The
# voice-alignment GPU trainer (Unsloth Studio on NVIDIA, unsloth-core on AMD)
# is a SEPARATE environment — never install it into .venv/. For Qwen3.5 support
# the trainer env also requires transformers v5 (Unsloth Studio ships 4.x by
# default). See docs/hardware.md#qwen35-trainer-prerequisites for the upgrade
# command and the mainline-GGUF conversion requirement.

# First-run wizard hand-off. Only offer it interactively (a TTY) and when not
# suppressed with --no-wizard. It writes config/kaine.operator.toml, detects the
# external services your chosen modules need (offering a consented install or
# setup guidance), and never boots the entity.
if [[ "$NO_WIZARD" -eq 0 ]] && [[ -t 0 ]] && [[ -t 1 ]]; then
  read -r -p "Run the first-run setup wizard now? [y/N] " _ans
  case "$_ans" in
    y|Y|yes|YES)
      "$PY" -m kaine.setup ;;
    *)
      echo "==> skipped. Run it later with: .venv/bin/python -m kaine.setup" ;;
  esac
else
  echo "==> run the first-run wizard with: .venv/bin/python -m kaine.setup"
fi
