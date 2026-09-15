#!/usr/bin/env bash
#
# The CUDA wheel index is host-resolved by kaine.wheel_index from the CPU
# architecture, the driver's CUDA version, the GPUs' compute capability and
# the unified-memory classification. Hosts with no usable CUDA wheel (e.g.
# Tegra/Jetson) resolve to the CPU index with a warning instead of receiving
# a wheel that fails at the first kernel launch. --index-url <URL> overrides
# the resolved CUDA index; it is ignored for --cpu/--rocm/--xpu/--mps.
# GPU preflight memory states (known-discrete, known-unified, unknown):
# see docs/accelerator-provisioning.md for details.
# KAINE installer: detects host hardware and installs PyTorch from the
# matching wheel index, then installs the rest of KAINE editable.
#
# Idempotent — safe to re-run. Run from the repo root.
#
#   bash scripts/install.sh           # auto-detect
#   bash scripts/install.sh --cpu     # force CPU wheels
#   bash scripts/install.sh --cuda    # force CUDA wheels (resolved via kaine.wheel_index)
#   bash scripts/install.sh --index-url URL  # force a specific CUDA wheel index
#   bash scripts/install.sh --rocm    # force ROCm wheels (rocm6.2)
#   bash scripts/install.sh --xpu     # force Intel XPU wheels
#   bash scripts/install.sh --mps     # force macOS MPS (default PyPI wheel)
#   bash scripts/install.sh --research # ALSO install the perception extras (.[perception])
#   bash scripts/install.sh --no-wizard # skip the interactive wizard
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
# Legacy fallback: used only when the host-resolved wheel-index probe
# (kaine.wheel_index) fails; the cuda flavor branch below normally overrides it.
NVIDIA_INDEX_URL="https://download.pytorch.org/whl/cu128"
ROCM_INDEX_URL="https://download.pytorch.org/whl/rocm6.2"
XPU_INDEX_URL="https://download.pytorch.org/whl/xpu"
CPU_INDEX_URL="https://download.pytorch.org/whl/cpu"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --index-url)
      # Operator override for the CUDA wheel index (consumed by the cuda flavor).
      if [ "$#" -lt 2 ]; then
        echo "install.sh: --index-url requires a URL argument" >&2
        exit 2
      fi
      INDEX_URL_OVERRIDE="$2"
      shift 2
      continue
      ;;
    --index-url=*)
      INDEX_URL_OVERRIDE="${1#--index-url=}"
      shift
      continue
      ;;
    --cpu)  FORCE="cpu";  shift ;;
    --cuda) FORCE="cuda"; shift ;;
    --rocm) FORCE="rocm"; shift ;;
    --xpu)  FORCE="xpu";  shift ;;
    --mps)  FORCE="mps";  shift ;;
    --python) PYTHON_BIN="$2"; shift 2 ;;
    --no-wizard) NO_WIZARD=1; shift ;;
    --research) RESEARCH=1; shift ;;
    --help|-h)
      sed -n '2,25p' "$0"; exit 0 ;;
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
  cuda)
    # Host-resolved CUDA wheel index (kaine.wheel_index). The resolver is
    # advisory: if it cannot run or its output is unusable, fall back to the
    # legacy hardcoded index below so the installer is never blocked.
    INDEX_URL="$NVIDIA_INDEX_URL"
    KAINE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)" || true
    RESOLVER_PY=""
    for _resolver_candidate in \
      ".venv/bin/python" \
      "${VENV_PY:-}" \
      "${VENV_DIR:-}/bin/python" \
      "${KAINE_ROOT}/.venv/bin/python"
    do
      if [ -n "$_resolver_candidate" ] && [ -x "$_resolver_candidate" ]; then
        RESOLVER_PY="$_resolver_candidate"
        break
      fi
    done
    if [ -z "$RESOLVER_PY" ] && command -v python3 >/dev/null 2>&1; then
      RESOLVER_PY="$(command -v python3)"
    fi
    RESOLVER_JSON=""
    if [ -n "$RESOLVER_PY" ]; then
      if [ -n "${INDEX_URL_OVERRIDE:-}" ]; then
        RESOLVER_JSON="$(cd "$KAINE_ROOT" 2>/dev/null && PYTHONPATH="$KAINE_ROOT${PYTHONPATH:+:$PYTHONPATH}" "$RESOLVER_PY" -m kaine.wheel_index --override "$INDEX_URL_OVERRIDE" 2>/dev/null || true)"
      else
        RESOLVER_JSON="$(cd "$KAINE_ROOT" 2>/dev/null && PYTHONPATH="$KAINE_ROOT${PYTHONPATH:+:$PYTHONPATH}" "$RESOLVER_PY" -m kaine.wheel_index 2>/dev/null || true)"
      fi
    fi
    RESOLVER_VARIANT=""
    RESOLVER_URL=""
    if [ -n "$RESOLVER_JSON" ] && [ -n "$RESOLVER_PY" ]; then
      RESOLVER_VARIANT="$(printf '%s' "$RESOLVER_JSON" | "$RESOLVER_PY" -c 'import json,sys; print(json.load(sys.stdin).get("variant",""))' 2>/dev/null || true)"
      RESOLVER_URL="$(printf '%s' "$RESOLVER_JSON" | "$RESOLVER_PY" -c 'import json,sys; print(json.load(sys.stdin).get("index_url",""))' 2>/dev/null || true)"
    fi
    if [ -n "$RESOLVER_URL" ]; then
      INDEX_URL="$RESOLVER_URL"
      if [ -n "${INDEX_URL_OVERRIDE:-}" ]; then
        INDEX_URL_SOURCE="operator override (--index-url)"
      else
        INDEX_URL_SOURCE="host-resolved decision table (kaine.wheel_index)"
      fi
      if [ "$RESOLVER_VARIANT" = "cpu" ]; then
        echo "WARNING: no usable CUDA wheel index exists for this host; using the CPU index returned by the wheel-index resolver." >&2
      fi
      printf '%s' "$RESOLVER_JSON" | "$RESOLVER_PY" -c 'import json,sys
d=json.load(sys.stdin)
probes=d.get("probes") or {}
for k in sorted(probes):
    v=probes[k]
    text=json.dumps(v,sort_keys=True) if isinstance(v,(dict,list)) else str(v)
    print("wheel-index probe {}: {}".format(k,text))
if d.get("variant")=="cpu":
    sys.stderr.write("WARNING: CUDA flavor requested but no usable CUDA wheel index exists for this host; using the CPU index.\n")
    for w in (d.get("warnings") or []):
        sys.stderr.write("WARNING: {}\n".format(w))
else:
    for w in (d.get("warnings") or []):
        print("wheel-index warning: {}".format(w))
' || true
      echo "wheel index: $INDEX_URL (source: $INDEX_URL_SOURCE)"
      echo "$RESOLVER_JSON"
    else
      echo "WARNING: CUDA wheel-index probe failed (kaine.wheel_index missing, exited non-zero, or produced unparseable output); using the legacy hardcoded default index $NVIDIA_INDEX_URL." >&2
      if [ -n "${INDEX_URL_OVERRIDE:-}" ]; then
        echo "WARNING: the requested --index-url override could not be applied because the resolver failed; continuing with the legacy default." >&2
      fi
    fi
  ;;
  rocm) INDEX_URL="$ROCM_INDEX_URL" ;;
  xpu)  INDEX_URL="$XPU_INDEX_URL" ;;
  cpu)  INDEX_URL="$CPU_INDEX_URL" ;;
  mps)  INDEX_URL="" ;;  # macOS MPS ships in the default PyPI wheel
  *) echo "unknown flavor $flavor" >&2; exit 3 ;;
esac

# An operator --index-url override applies only to the CUDA flavor; every
# other flavor keeps its fixed wheel index and never consults the resolver.
if [ -n "${INDEX_URL_OVERRIDE:-}" ] && [ "$flavor" != "cuda" ]; then
  echo "NOTICE: ignoring --index-url for flavor '$flavor' (only the cuda flavor accepts an operator index override)." >&2
fi

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
