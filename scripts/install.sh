#!/usr/bin/env bash
#
# The CUDA wheel index is host-resolved by kaine.wheel_index from the CPU
# architecture, the driver's CUDA version, the GPUs' compute capability and
# the unified-memory classification. JetPack 7 hosts (driver CUDA >= 13.0)
# resolve to a cu13x index and run a GPU-vs-CPU numerical self-test with a CPU
# fallback; JetPack 6 hosts resolve to CPU wheels with a note. --index-url
# <URL> overrides the resolved CUDA index; it is ignored for --cpu/--rocm/--xpu/--mps.
# GPU preflight memory states (known-discrete, known-unified, unknown):
# see docs/accelerator-provisioning.md for details.
#
# KAINE installer: detects host hardware and installs PyTorch from the
# matching wheel index, then installs the rest of KAINE editable.
#
# The torch version spec is read from pyproject.toml (the first project
# dependency line that starts with "torch" followed by a version operator).
# Use --print-torch-spec to print the resolved spec and exit without touching
# the environment.
#
# Idempotent — safe to re-run. Run from the repo root.
#
# Environment:
#   KAINE_VENV_DIR    virtualenv directory to use (default: .venv; may be
#                     absolute or relative to the repo root). Created if absent.
#
# Flags:
#   bash scripts/install.sh           # auto-detect
#   bash scripts/install.sh --cpu     # force CPU wheels
#   bash scripts/install.sh --cuda    # force CUDA wheels (resolved via kaine.wheel_index)
#   bash scripts/install.sh --index-url URL  # force a specific CUDA wheel index
#   bash scripts/install.sh --rocm    # force ROCm wheels (host-resolved)
#   bash scripts/install.sh --xpu     # force Intel XPU wheels
#   bash scripts/install.sh --mps     # force macOS MPS (default PyPI wheel)
#   bash scripts/install.sh --research # ALSO install the perception extras (.[perception])
#   bash scripts/install.sh --no-wizard # skip the interactive wizard
#   bash scripts/install.sh --print-torch-spec # print the resolved torch spec and exit
#   bash scripts/install.sh --retry-gpu # delete the GPU self-test fallback marker and retry the resolved CUDA index
#
# The installer pins the installed torch stack (torch, torchvision and, with
# --research, torchaudio) in $KAINE_VENV_DIR/kaine-torch-constraints.txt and
# passes that constraints file to every subsequent pip install, so later
# editable installs cannot re-resolve torch from a different index.
#
# On a host where the resolved CUDA wheels fail the GPU numerical self-test
# (unified-memory devices), the installer falls back to CPU wheels and writes
# $KAINE_VENV_DIR/kaine-accel-fallback.json. Later runs skip the GPU attempt
# and keep CPU wheels while that file matches the resolved index/torch version.
# Use --retry-gpu to delete the marker and attempt the GPU index again.
#
# The default install stays lean (no cv2/av/funasr). The venv is created at
# $KAINE_VENV_DIR/ if absent. Use --python /path/to/python to override the
# interpreter the venv is built from.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
ROOT="$(pwd)"

TORCH_SPEC_LINE=$(sed -n '/^[[:space:]]*"torch[<>=!~ ]/p' pyproject.toml | head -n 1)
TORCH_SPEC=$(printf '%s' "$TORCH_SPEC_LINE" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//;s/^"//;s/",$//;s/"$//')
if [[ -z "$TORCH_SPEC" ]]; then
  echo "install.sh: could not find torch dependency in pyproject.toml" >&2
  exit 1
fi

PYTHON_BIN="python3"
FORCE=""
NO_WIZARD=0
RESEARCH=0
RETRY_GPU=0
EXTRAS="full"
# Pins filled by host-aware wheel-index resolution for CUDA and ROCm.
TORCH_PIN=""
TV_PIN=""
TA_PIN=""
SELFTEST=""
TA_UNAVAILABLE="false"
# Legacy fallback: used only when the host-resolved wheel-index probe
# (kaine.wheel_index) fails; the cuda flavor branch below normally overrides it.
# cu126 is the CUDA index with the widest driver compatibility that carries
# the project's torch floor (cu128 stops at torch 2.11); the host-aware
# resolver still chooses per host when it is available.
NVIDIA_INDEX_URL="https://download.pytorch.org/whl/cu126"
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
    --retry-gpu) RETRY_GPU=1; shift ;;
    --extras)
      if [ "$#" -lt 2 ]; then
        echo "install.sh: --extras requires a comma-separated list" >&2
        exit 2
      fi
      EXTRAS="$2"
      shift 2
      continue
      ;;
    --extras=*)
      EXTRAS="${1#--extras=}"
      shift
      continue
      ;;
    --print-torch-spec)
      printf '%s\n' "$TORCH_SPEC"
      exit 0
      ;;
    --help|-h)
      cat <<'EOF'
bash scripts/install.sh           # auto-detect
bash scripts/install.sh --cpu     # force CPU wheels
bash scripts/install.sh --cuda    # force CUDA wheels (resolved via kaine.wheel_index)
bash scripts/install.sh --index-url URL  # force a specific CUDA wheel index
bash scripts/install.sh --rocm    # force ROCm wheels (host-resolved)
bash scripts/install.sh --xpu     # force Intel XPU wheels
bash scripts/install.sh --mps     # force macOS MPS (default PyPI wheel)
bash scripts/install.sh --research # ALSO install the perception extras (.[perception])
bash scripts/install.sh --no-wizard # skip the interactive wizard
bash scripts/install.sh --print-torch-spec # print the resolved torch spec and exit
bash scripts/install.sh --retry-gpu # delete the GPU self-test fallback marker and retry the resolved CUDA index
bash scripts/install.sh --extras core,memory # install a chosen extra set instead of full
EOF
      exit 0 ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
done

VENV_DIR="${KAINE_VENV_DIR:-.venv}"

# Normalise to an absolute path so every downstream reference (venv
# creation, resolver candidate selection, constraints file) points at the same
# directory regardless of whether KAINE_VENV_DIR was absolute.
if [[ ! "$VENV_DIR" = /* ]]; then
  VENV_DIR="$ROOT/$VENV_DIR"
fi
ACCEL_FALLBACK_FILE="$VENV_DIR/kaine-accel-fallback.json"

# Honour an explicit request to clear the GPU fallback marker before any
# host resolution happens.
if [[ "$RETRY_GPU" -eq 1 ]] && [[ -f "$ACCEL_FALLBACK_FILE" ]]; then
  echo "==> --retry-gpu: clearing previous GPU fallback marker"
  rm -f "$ACCEL_FALLBACK_FILE"
fi

if [[ ! -d "$VENV_DIR" ]]; then
  echo "==> creating venv at $VENV_DIR/ using $PYTHON_BIN"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

PIP="$VENV_DIR/bin/pip"
PY="$VENV_DIR/bin/python"

write_torch_constraints() {
  local out="$1"
  "$PY" - "$out" <<'PY'
import importlib.metadata as md
import sys
names = ["torch", "torchvision", "torchaudio"]
out_path = sys.argv[1]
with open(out_path, "w") as f:
    pins = []
    for name in names:
        try:
            ver = md.version(name)
            f.write(f"{name}=={ver}\n")
            pins.append(f"{name}=={ver}")
        except md.PackageNotFoundError:
            pass
    if pins:
        print(" ".join(pins))
    else:
        print("(none installed)")
PY
}

_index_tag() {
  local url="$1"
  url="${url%/}"
  echo "${url##*/}"
}

# Normalize a gfx name token from rocminfo / rocm_agent_enumerator output.
# Input may include leading/trailing whitespace and an optional ':' feature
# suffix.  Prints the cleaned name when it names a real gfx target; prints
# nothing for gfx000, -generic targets, or otherwise invalid tokens.
_normalize_gfx_name() {
  local raw="$1"
  # Trim leading and trailing whitespace.
  raw="${raw#"${raw%%[![:space:]]*}"}"
  raw="${raw%"${raw##*[![:space:]]}"}"
  # Strip feature suffixes (anything from the first ':' onward).
  raw="${raw%%:*}"
  # Drop the reserved/invalid targets.
  [ "$raw" = "gfx000" ] && return
  case "$raw" in *-generic) return ;; esac
  # Only accept gfx<hex>.
  [[ "$raw" =~ ^gfx[0-9a-f]+$ ]] || return
  printf '%s\n' "$raw"
}

_is_pytorch_whl_url() {
  local url="$1"
  [[ "$url" == https://download.pytorch.org/whl/* ]]
}

_tags_match() {
  local installed_tag="$1"
  local target_tag="$2"
  local url="$3"
  if ! _is_pytorch_whl_url "$url"; then
    return 0
  fi
  if [[ -z "$installed_tag" ]]; then
    installed_tag="cpu"
  fi
  [[ "$installed_tag" == "$target_tag" ]]
}

_current_torch_base() {
  "$PY" -c "import torch; print(torch.__version__.split('+',1)[0])" 2>/dev/null || true
}

_installed_torch_tag() {
  "$PY" -c "import torch, sys; v=torch.__version__; sys.stdout.write(v.split('+',1)[1] if '+' in v else '')" 2>/dev/null || true
}

_package_installed() {
  local pkg="$1"
  "$PY" -c "import importlib.metadata as md; md.version('$pkg')" >/dev/null 2>&1
}

_package_version() {
  local pkg="$1"
  "$PY" -c "import importlib.metadata as md; print(md.version('$pkg'))" 2>/dev/null || true
}

_read_accel_fallback_marker() {
  local file="$1"
  if [ -f "$file" ]; then
    "$PY" -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("index_url","NA"), d.get("torch","NA"))' "$file" 2>/dev/null
  fi
}

_write_accel_fallback_marker() {
  local file="$1" url="$2" torch="$3" reason="$4"
  "$PY" -c 'import json,sys,datetime; d={"reason":sys.argv[4],"index_url":sys.argv[2],"torch":sys.argv[3],"date":datetime.datetime.now(datetime.timezone.utc).isoformat()}; json.dump(d,open(sys.argv[1],"w"))' "$file" "$url" "$torch" "$reason"
}

# Shared implementation for torchaudio install paths used by audio-stack
# coherence and by --research.
_install_torchaudio() {
  local mode="$1"
  local idx="$2"
  local pin="$3"
  local cfile="$4"
  local force="$5"
  local label=""
  local extra=""
  if [[ "$mode" == "research" ]]; then
    label="[--research] "
  else
    extra=" (audio-stack coherence)"
  fi
  if [[ -n "$pin" ]]; then
    echo "==> ${label}installing torchaudio==${pin} from ${idx}${extra}"
    "$PIP" install $force --index-url "$idx" -c "$cfile" "torchaudio==${pin}"
  elif [[ -z "$idx" ]]; then
    echo "==> ${label}installing torchaudio (default PyPI wheel for MPS)${extra}"
    "$PIP" install $force -c "$cfile" torchaudio
  else
    echo "==> ${label}installing torchaudio from ${idx}${extra}"
    "$PIP" install $force --index-url "$idx" -c "$cfile" torchaudio
  fi
}

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

NEED_TORCH=0
if [[ ",${EXTRAS}," == *",core,"* ]] || [[ ",${EXTRAS}," == *",full,"* ]]; then
  NEED_TORCH=1
fi

if [[ "$NEED_TORCH" -eq 1 ]]; then
  # Audio-stack coherence: if torchaudio is already installed and this is not a
  # --research run, keep the audio stack coherent on every flavor. The resolver
  # is asked for a torchaudio pin whenever one is needed.
NEED_TORCHAUDIO=0
if [[ "$RESEARCH" -eq 0 ]] && _package_installed torchaudio; then
  NEED_TORCHAUDIO=1
  echo "==> torchaudio is installed; keeping the audio stack coherent (resolving with --need-torchaudio)"
fi

# Resolver helper for the fixed-index flavors (cpu, xpu). Sets RESOLVER_PY,
# RESOLVER_JSON, RESOLVER_URL, RESOLVER_ARCH_RECORDED, TORCH_PIN, TV_PIN and
# TA_PIN. Returns 0 when a usable index_url was returned, 1 when the resolver
# returned a null index_url (RESOLVER_ARCH_RECORDED indicates whether the
# architecture is recorded), and 2 when the resolver produced no output or
# unparseable JSON.
_resolve_fixed_flavor() {
  local flavor="$1"
  local kaine_root resolver_py resolver_json
  local extra_args=()
  kaine_root="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)" || true
  resolver_py=""
  for _resolver_candidate in \
    "${VENV_DIR}/bin/python" \
    "${VENV_PY:-}"
  do
    if [ -n "$_resolver_candidate" ] && [ -x "$_resolver_candidate" ]; then
      resolver_py="$_resolver_candidate"
      break
    fi
  done
  if [ -z "$resolver_py" ] && command -v python3 >/dev/null 2>&1; then
    resolver_py="$(command -v python3)"
  fi
  if [ "$RESEARCH" -eq 1 ] || [ "$NEED_TORCHAUDIO" -eq 1 ]; then
    extra_args+=("--need-torchaudio")
  fi

  RESOLVER_PY="$resolver_py"
  RESOLVER_JSON=""
  if [ -n "$resolver_py" ]; then
    RESOLVER_JSON="$(cd "$kaine_root" 2>/dev/null && PYTHONPATH="$kaine_root${PYTHONPATH:+:$PYTHONPATH}" "$resolver_py" -m kaine.wheel_index --flavor "$flavor" ${extra_args[@]+"${extra_args[@]}"} 2>/dev/null || true)"
  fi

  RESOLVER_URL=""
  RESOLVER_ARCH_RECORDED="false"
  TORCH_PIN=""
  TV_PIN=""
  TA_PIN=""
  local _parsed=0
  if [ -n "$RESOLVER_JSON" ] && [ -n "$resolver_py" ]; then
    if printf '%s' "$RESOLVER_JSON" | "$resolver_py" -c 'import json,sys; json.load(sys.stdin)' >/dev/null 2>&1; then
      _parsed=1
    fi
  fi
  if [ "$_parsed" -eq 1 ]; then
    RESOLVER_URL="$(printf '%s' "$RESOLVER_JSON" | "$resolver_py" -c 'import json,sys; d=json.load(sys.stdin); v=d.get("index_url"); print("" if v is None else v)' 2>/dev/null || true)"
    RESOLVER_ARCH_RECORDED="$(printf '%s' "$RESOLVER_JSON" | "$resolver_py" -c 'import json,sys; d=json.load(sys.stdin); print("true" if d.get("arch_recorded") else "false")' 2>/dev/null || true)"
    TORCH_PIN="$(printf '%s' "$RESOLVER_JSON" | "$resolver_py" -c 'import json,sys; d=json.load(sys.stdin); v=d.get("torch_version"); print("" if v is None else v)' 2>/dev/null || true)"
    TV_PIN="$(printf '%s' "$RESOLVER_JSON" | "$resolver_py" -c 'import json,sys; d=json.load(sys.stdin); v=d.get("torchvision_version"); print("" if v is None else v)' 2>/dev/null || true)"
    TA_PIN="$(printf '%s' "$RESOLVER_JSON" | "$resolver_py" -c 'import json,sys; d=json.load(sys.stdin); v=d.get("torchaudio_version"); print("" if v is None else v)' 2>/dev/null || true)"
  fi

  if [ -n "$RESOLVER_URL" ]; then
    return 0
  fi
  if [ "$_parsed" -eq 1 ]; then
    return 1
  fi
  return 2
}

# Print resolver warnings from RESOLVER_JSON for a fixed-index flavor.
_print_fixed_flavor_warnings() {
  if [ -n "$RESOLVER_JSON" ] && [ -n "$RESOLVER_PY" ]; then
    printf '%s' "$RESOLVER_JSON" | "$RESOLVER_PY" -c 'import json,sys
d=json.load(sys.stdin)
for w in (d.get("warnings") or []):
    print("wheel-index warning: {}".format(w))
' || true
  fi
}

# Print resolver warnings from RESOLVER_JSON to stderr with a WARNING: prefix.
_print_resolver_warnings_to_stderr() {
  if [ -n "$RESOLVER_JSON" ] && [ -n "$RESOLVER_PY" ]; then
    printf '%s' "$RESOLVER_JSON" | "$RESOLVER_PY" -c 'import json,sys
d=json.load(sys.stdin)
for w in (d.get("warnings") or []):
    sys.stderr.write("WARNING: {}\n".format(w))
' || true
  fi
}

case "$flavor" in
  cuda)
    # Host-resolved CUDA wheel index (kaine.wheel_index). The resolver is
    # advisory: if it cannot run or its output is unusable, fall back to the
    # legacy hardcoded index below so the installer is never blocked.
    INDEX_URL="$NVIDIA_INDEX_URL"
    GPU_INDEX_URL="$NVIDIA_INDEX_URL"
    KAINE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)" || true
    RESOLVER_PY=""
    for _resolver_candidate in \
      "${VENV_DIR}/bin/python" \
      "${VENV_PY:-}"
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
    resolver_extra_args=()
    if [ "$RESEARCH" -eq 1 ] || [ "$NEED_TORCHAUDIO" -eq 1 ]; then
      resolver_extra_args+=("--need-torchaudio")
    fi
    if [ -n "${INDEX_URL_OVERRIDE:-}" ]; then
      RESOLVER_JSON="$(cd "$KAINE_ROOT" 2>/dev/null && PYTHONPATH="$KAINE_ROOT${PYTHONPATH:+:$PYTHONPATH}" "$RESOLVER_PY" -m kaine.wheel_index --override "$INDEX_URL_OVERRIDE" ${resolver_extra_args[@]+"${resolver_extra_args[@]}"} 2>/dev/null || true)"
    else
      RESOLVER_JSON="$(cd "$KAINE_ROOT" 2>/dev/null && PYTHONPATH="$KAINE_ROOT${PYTHONPATH:+:$PYTHONPATH}" "$RESOLVER_PY" -m kaine.wheel_index ${resolver_extra_args[@]+"${resolver_extra_args[@]}"} 2>/dev/null || true)"
    fi
    RESOLVER_VARIANT=""
    RESOLVER_URL=""
    if [ -n "$RESOLVER_JSON" ] && [ -n "$RESOLVER_PY" ]; then
      RESOLVER_VARIANT="$(printf '%s' "$RESOLVER_JSON" | "$RESOLVER_PY" -c 'import json,sys; d=json.load(sys.stdin); v=d.get("variant"); print("" if v is None else v)' 2>/dev/null || true)"
      RESOLVER_URL="$(printf '%s' "$RESOLVER_JSON" | "$RESOLVER_PY" -c 'import json,sys; d=json.load(sys.stdin); v=d.get("index_url"); print("" if v is None else v)' 2>/dev/null || true)"
      TORCH_PIN="$(printf '%s' "$RESOLVER_JSON" | "$RESOLVER_PY" -c 'import json,sys; d=json.load(sys.stdin); v=d.get("torch_version"); print("" if v is None else v)' 2>/dev/null || true)"
      TV_PIN="$(printf '%s' "$RESOLVER_JSON" | "$RESOLVER_PY" -c 'import json,sys; d=json.load(sys.stdin); v=d.get("torchvision_version"); print("" if v is None else v)' 2>/dev/null || true)"
      TA_PIN="$(printf '%s' "$RESOLVER_JSON" | "$RESOLVER_PY" -c 'import json,sys; d=json.load(sys.stdin); v=d.get("torchaudio_version"); print("" if v is None else v)' 2>/dev/null || true)"
      SELFTEST="$(printf '%s' "$RESOLVER_JSON" | "$RESOLVER_PY" -c 'import json,sys; print("true" if json.load(sys.stdin).get("selftest_required") else "false")' 2>/dev/null || true)"
      TA_UNAVAILABLE="$(printf '%s' "$RESOLVER_JSON" | "$RESOLVER_PY" -c 'import json,sys; print("true" if json.load(sys.stdin).get("torchaudio_unavailable") else "false")' 2>/dev/null || true)"
    fi
    if [ -n "$RESOLVER_URL" ]; then
      if [ "$RESEARCH" -eq 1 ] && [ "$TA_UNAVAILABLE" = "true" ]; then
        echo "install: --research needs torchaudio, but $RESOLVER_URL publishes no torchaudio for torch ${TORCH_PIN}; choose a different --index-url or drop --research" >&2
        exit 1
      fi
      INDEX_URL="$RESOLVER_URL"
      GPU_INDEX_URL="$RESOLVER_URL"
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
      if [ -n "$TORCH_PIN" ]; then
        echo "==> resolved torch $TORCH_PIN / torchvision $TV_PIN from $INDEX_URL"
      fi
      echo "$RESOLVER_JSON"
    else
      echo "WARNING: CUDA wheel-index probe failed (kaine.wheel_index missing, exited non-zero, or produced unparseable output); using the legacy hardcoded default index $NVIDIA_INDEX_URL." >&2
      if [ -n "${INDEX_URL_OVERRIDE:-}" ]; then
        echo "WARNING: the requested --index-url override could not be applied because the resolver failed; continuing with the legacy default." >&2
      fi
    fi

    # Self-test fallback marker: if a previous run recorded a GPU self-test
    # failure for the exact index/torch version we just resolved, skip the
    # GPU attempt and keep CPU wheels unless the operator asked to retry.
    if [ -f "$ACCEL_FALLBACK_FILE" ] && [ "$RETRY_GPU" -ne 1 ]; then
      marker=$(_read_accel_fallback_marker "$ACCEL_FALLBACK_FILE" || true)
      if [ -n "$marker" ]; then
        marker_url=$(printf '%s' "$marker" | cut -d' ' -f1)
        marker_torch=$(printf '%s' "$marker" | cut -d' ' -f2)
        current_target_torch="${TORCH_PIN:-$(_current_torch_base)}"
        if [ "$marker_url" = "$GPU_INDEX_URL" ] && [ "$marker_torch" = "$current_target_torch" ] && [ -n "$current_target_torch" ]; then
          echo "NOTICE: GPU self-test previously failed for this index/torch version; recorded in $ACCEL_FALLBACK_FILE. Using CPU wheels. Use --retry-gpu to attempt the GPU index again." >&2
          INDEX_URL="$CPU_INDEX_URL"
          SELFTEST="false"
        fi
      fi
    fi
  ;;
  rocm)
    # Host-resolved ROCm wheel index (kaine.wheel_index). Never fall back to a
    # hardcoded index: if the resolver cannot find a wheel for this ROCm stack,
    # the install stops with a clear error.
    ROCM_VERSION="${KAINE_ROCM_VERSION:-}"
    if [ -z "$ROCM_VERSION" ] && [ -r /opt/rocm/.info/version ]; then
      ROCM_VERSION="$(grep -oE '[0-9]+\.[0-9]+' /opt/rocm/.info/version | head -n 1 || true)"
    fi
    if [ -z "$ROCM_VERSION" ]; then
      echo "install.sh: could not determine ROCm version. Set KAINE_ROCM_VERSION (e.g. 7.2) and re-run." >&2
      exit 1
    fi

    ROCM_GFX="${KAINE_ROCM_GFX:-}"
    ROCM_GFX_SOURCE=""
    if [ -n "$ROCM_GFX" ]; then
      ROCM_GFX_SOURCE="KAINE_ROCM_GFX"
    else
      ROCM_GFX_SOURCE="none"
      _gfx_list=""
      if command -v rocminfo >/dev/null 2>&1; then
        _gfx_list="$(rocminfo 2>/dev/null | sed -nE 's/^[[:space:]]*Name:[[:space:]]+([^[:space:]]+).*/\1/p' | while read -r name; do
          _normalize_gfx_name "$name"
        done | awk '!seen[$0]++' | tr '\n' ',' | sed 's/,$//')" || true
        if [ -n "$_gfx_list" ]; then
          ROCM_GFX="$_gfx_list"
          ROCM_GFX_SOURCE="rocminfo"
        fi
      fi
      if [ -z "$ROCM_GFX" ] && command -v rocm_agent_enumerator >/dev/null 2>&1; then
        _gfx_list="$(rocm_agent_enumerator 2>/dev/null | while read -r name; do
          name="$(_normalize_gfx_name "$name")"
          [ -n "$name" ] && printf '%s\n' "$name"
        done | awk '!seen[$0]++' | tr '\n' ',' | sed 's/,$//')" || true
        if [ -n "$_gfx_list" ]; then
          ROCM_GFX="$_gfx_list"
          ROCM_GFX_SOURCE="rocm_agent_enumerator"
        fi
      fi
    fi

    KAINE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)" || true
    RESOLVER_PY=""
    for _resolver_candidate in \
      "${VENV_DIR}/bin/python" \
      "${VENV_PY:-}"
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
    resolver_extra_args=()
    if [ "$RESEARCH" -eq 1 ] || [ "$NEED_TORCHAUDIO" -eq 1 ]; then
      resolver_extra_args+=("--need-torchaudio")
    fi
    if [ -n "$ROCM_GFX" ]; then
      RESOLVER_JSON="$(cd "$KAINE_ROOT" 2>/dev/null && PYTHONPATH="$KAINE_ROOT${PYTHONPATH:+:$PYTHONPATH}" "$RESOLVER_PY" -m kaine.wheel_index --rocm-version "$ROCM_VERSION" --gfx "$ROCM_GFX" ${resolver_extra_args[@]+"${resolver_extra_args[@]}"} 2>/dev/null || true)"
    else
      RESOLVER_JSON="$(cd "$KAINE_ROOT" 2>/dev/null && PYTHONPATH="$KAINE_ROOT${PYTHONPATH:+:$PYTHONPATH}" "$RESOLVER_PY" -m kaine.wheel_index --rocm-version "$ROCM_VERSION" ${resolver_extra_args[@]+"${resolver_extra_args[@]}"} 2>/dev/null || true)"
    fi

    RESOLVER_URL=""
    if [ -n "$RESOLVER_JSON" ] && [ -n "$RESOLVER_PY" ]; then
      RESOLVER_URL="$(printf '%s' "$RESOLVER_JSON" | "$RESOLVER_PY" -c 'import json,sys; d=json.load(sys.stdin); v=d.get("index_url"); print("" if v is None else v)' 2>/dev/null || true)"
      TORCH_PIN="$(printf '%s' "$RESOLVER_JSON" | "$RESOLVER_PY" -c 'import json,sys; d=json.load(sys.stdin); v=d.get("torch_version"); print("" if v is None else v)' 2>/dev/null || true)"
      TV_PIN="$(printf '%s' "$RESOLVER_JSON" | "$RESOLVER_PY" -c 'import json,sys; d=json.load(sys.stdin); v=d.get("torchvision_version"); print("" if v is None else v)' 2>/dev/null || true)"
      TA_PIN="$(printf '%s' "$RESOLVER_JSON" | "$RESOLVER_PY" -c 'import json,sys; d=json.load(sys.stdin); v=d.get("torchaudio_version"); print("" if v is None else v)' 2>/dev/null || true)"
      SELFTEST="$(printf '%s' "$RESOLVER_JSON" | "$RESOLVER_PY" -c 'import json,sys; print("true" if json.load(sys.stdin).get("selftest_required") else "false")' 2>/dev/null || true)"
      TA_UNAVAILABLE="$(printf '%s' "$RESOLVER_JSON" | "$RESOLVER_PY" -c 'import json,sys; print("true" if json.load(sys.stdin).get("torchaudio_unavailable") else "false")' 2>/dev/null || true)"
    fi

    if [ -z "$RESOLVER_URL" ]; then
      echo "install.sh: no ROCm wheel index carries a torch in the project's tested range for ROCm $ROCM_VERSION (gfx: ${ROCM_GFX:-auto-detected})." >&2
      printf '%s' "$RESOLVER_JSON" | "$RESOLVER_PY" -c 'import json,sys
d=json.load(sys.stdin)
for w in (d.get("warnings") or []):
    sys.stderr.write("WARNING: {}\n".format(w))
' || true
      exit 1
    fi

    INDEX_URL="$RESOLVER_URL"
    echo "==> ROCm version: $ROCM_VERSION; gfx targets: ${ROCM_GFX:-none detected} (source: $ROCM_GFX_SOURCE)"
    printf '%s' "$RESOLVER_JSON" | "$RESOLVER_PY" -c 'import json,sys
d=json.load(sys.stdin)
for w in (d.get("warnings") or []):
    print("wheel-index warning: {}".format(w))
' || true
    echo "wheel index: $INDEX_URL (source: host-resolved ROCm decision table)"
    if [ -n "$TORCH_PIN" ]; then
      echo "==> resolved torch $TORCH_PIN / torchvision $TV_PIN from $INDEX_URL"
    fi
  ;;
  xpu)
    _rc=0
    _resolve_fixed_flavor xpu || _rc=$?
    if [ $_rc -eq 0 ]; then
      INDEX_URL="$RESOLVER_URL"
      echo "wheel index: $INDEX_URL (source: host-resolved xpu wheel data)"
      if [ -n "$TORCH_PIN" ]; then
        echo "==> resolved torch $TORCH_PIN / torchvision $TV_PIN from $INDEX_URL"
      fi
      _print_fixed_flavor_warnings xpu
    elif [ $_rc -eq 1 ]; then
      echo "install: no xpu wheel index carries a torch in the project's tested range for this architecture." >&2
      _print_resolver_warnings_to_stderr
      exit 1
    else
      echo "install: the wheel-index resolver could not run; refusing to install xpu wheels without resolved pins." >&2
      exit 1
    fi
    ;;
  cpu)
    _rc=0
    _resolve_fixed_flavor cpu || _rc=$?
    if [ $_rc -eq 0 ]; then
      INDEX_URL="$RESOLVER_URL"
      echo "wheel index: $INDEX_URL (source: host-resolved cpu wheel data)"
      if [ -n "$TORCH_PIN" ]; then
        echo "==> resolved torch $TORCH_PIN / torchvision $TV_PIN from $INDEX_URL"
      fi
      _print_fixed_flavor_warnings cpu
    elif [ $_rc -eq 1 ] && [ "$RESOLVER_ARCH_RECORDED" = "true" ]; then
      echo "install: no cpu wheel index carries a torch in the project's tested range for this architecture." >&2
      _print_resolver_warnings_to_stderr
      exit 1
    elif [ $_rc -eq 1 ]; then
      echo "WARNING: no cpu wheel data is recorded for this architecture; installing unpinned from the fixed CPU index $CPU_INDEX_URL." >&2
      _print_resolver_warnings_to_stderr
      INDEX_URL="$CPU_INDEX_URL"
    else
      echo "WARNING: CPU wheel-index pins could not be resolved; using the fixed CPU index $CPU_INDEX_URL." >&2
      INDEX_URL="$CPU_INDEX_URL"
    fi
    ;;
  mps)  INDEX_URL="" ;;  # macOS MPS ships in the default PyPI wheel
  *) echo "unknown flavor $flavor" >&2; exit 3 ;;
esac

# An operator --index-url override applies only to the CUDA flavor; every
# other flavor keeps the wheel index chosen above (resolved from recorded wheel
# data for cpu, xpu and rocm; the default PyPI index for mps).
if [ -n "${INDEX_URL_OVERRIDE:-}" ] && [ "$flavor" != "cuda" ]; then
  echo "NOTICE: ignoring --index-url for flavor '$flavor' (only the cuda flavor accepts an operator index override)." >&2
fi

# The effective target flavor is the flavor of the index that will actually
# be installed from.  When the resolver or a GPU self-test fallback marker
# routes a cuda request to the CPU index, the target flavor becomes cpu.
EFFECTIVE_TARGET_FLAVOR="$flavor"
if [[ -n "$INDEX_URL" ]] && [[ "$INDEX_URL" == "$CPU_INDEX_URL" ]]; then
  EFFECTIVE_TARGET_FLAVOR="cpu"
fi

# If torchaudio must stay coherent and the chosen index cannot provide one,
# stop before touching torch.
if [[ "$NEED_TORCHAUDIO" -eq 1 ]] && [[ "$TA_UNAVAILABLE" == "true" ]]; then
  echo "install: torchaudio is installed, but $INDEX_URL publishes no torchaudio for torch ${TORCH_PIN}; choose a different --index-url, or uninstall torchaudio first to drop the audio stack" >&2
  exit 1
fi

# Idempotent torch install: probe which flavor is currently installed.
_FLAVOR_PROBE='
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
'

need_install=1
installed_torch_base=""
FORCE_REINSTALL_FLAG=""
if "$PY" -c "import torch; import sys; sys.exit(0 if torch.__version__.startswith('2.') else 1)" 2>/dev/null; then
  installed_flavor=$("$PY" -c "$_FLAVOR_PROBE" 2>/dev/null || echo "unknown")
  installed_torch_base=$("$PY" -c "import torch; print(torch.__version__.split('+',1)[0])" 2>/dev/null || true)
  if [[ "$installed_flavor" == "$EFFECTIVE_TARGET_FLAVOR" ]]; then
    if [[ -n "$TORCH_PIN" ]] && [[ "$installed_torch_base" != "$TORCH_PIN" ]]; then
      echo "==> torch installed with base version $installed_torch_base but want $TORCH_PIN; reinstalling"
    else
      echo "==> torch already installed at the right flavor ($installed_flavor); skipping torch install"
      need_install=0
    fi
  else
    echo "==> torch installed with flavor '$installed_flavor' but want '$EFFECTIVE_TARGET_FLAVOR'; reinstalling"
    FORCE_REINSTALL_FLAG="--force-reinstall"
  fi
  if _is_pytorch_whl_url "$INDEX_URL"; then
    target_tag=$(_index_tag "$INDEX_URL")
    installed_tag=$(_installed_torch_tag)
    if [[ -z "$installed_tag" ]]; then
      installed_tag="cpu"
    fi
    if [ "$installed_tag" != "$target_tag" ]; then
      echo "==> installed torch build tag '$installed_tag' differs from target index tag '$target_tag'; forcing reinstall"
      FORCE_REINSTALL_FLAG="--force-reinstall"
      need_install=1
    fi
  fi
fi

if [[ "$need_install" -eq 1 ]]; then
  if [[ -n "$TORCH_PIN" ]]; then
    if [[ -n "$TV_PIN" ]]; then
      echo "==> installing torch==$TORCH_PIN torchvision==$TV_PIN from $INDEX_URL"
      "$PIP" install $FORCE_REINSTALL_FLAG --index-url "$INDEX_URL" "torch==$TORCH_PIN" "torchvision==$TV_PIN"
    else
      echo "==> installing torch==$TORCH_PIN torchvision from $INDEX_URL"
      "$PIP" install $FORCE_REINSTALL_FLAG --index-url "$INDEX_URL" "torch==$TORCH_PIN" torchvision
    fi
  elif [[ "$flavor" == "mps" ]]; then
    echo "==> installing $TORCH_SPEC torchvision (default PyPI wheel for MPS)"
    "$PIP" install $FORCE_REINSTALL_FLAG "$TORCH_SPEC" torchvision
  else
    echo "==> installing $TORCH_SPEC torchvision from $INDEX_URL"
    "$PIP" install $FORCE_REINSTALL_FLAG --index-url "$INDEX_URL" "$TORCH_SPEC" torchvision
  fi
fi

# GPU numerical self-test for host-resolved unified-memory wheels.
if [[ "$SELFTEST" == "true" ]]; then
  echo "==> running GPU numerical self-test"
  _selftest_rc=0
  "$PY" -m kaine.accel_selftest || _selftest_rc=$?
  if [[ "$_selftest_rc" -ne 0 ]]; then
    if [[ "$_selftest_rc" -eq 1 ]]; then
      echo "WARNING: the GPU wheels failed the numerical self-test on this unified-memory device; CPU wheels will be installed instead." >&2
      _selftest_reason="GPU numerical self-test failed"
    else
      echo "WARNING: the GPU numerical self-test could not run (exit $_selftest_rc); CPU wheels will be installed instead." >&2
      _selftest_reason="GPU numerical self-test could not run (exit $_selftest_rc)"
    fi
    if [[ -n "$TV_PIN" ]]; then
      "$PIP" install --force-reinstall --index-url "$CPU_INDEX_URL" "torch==$TORCH_PIN" "torchvision==$TV_PIN"
    else
      "$PIP" install --force-reinstall --index-url "$CPU_INDEX_URL" "torch==$TORCH_PIN" torchvision
    fi
    INDEX_URL="$CPU_INDEX_URL"
    _write_accel_fallback_marker "$ACCEL_FALLBACK_FILE" "$GPU_INDEX_URL" "$TORCH_PIN" "$_selftest_reason"
  else
    echo "==> GPU numerical self-test passed"
  fi
fi

# Ensure the constraints file never pins a torchaudio that does not belong to
# the resolved stack. If torchaudio is installed, keep it only when the base
# version matches the resolved TA pin and the local tag matches the target
# index tag (untagged wheels count as cpu); otherwise uninstall it.
if _package_installed torchaudio; then
  installed_ta=$(_package_version torchaudio)
  installed_ta_base=${installed_ta%%+*}
  installed_ta_tag=${installed_ta#*+}
  if [[ "$installed_ta" == "$installed_ta_base" ]]; then
    installed_ta_tag=""
  fi
  if [[ -z "$TA_PIN" ]] || [[ "$installed_ta_base" != "$TA_PIN" ]] || ! _tags_match "$installed_ta_tag" "$(_index_tag "$INDEX_URL")" "$INDEX_URL"; then
    echo "==> uninstalling stale torchaudio $installed_ta (target pin: ${TA_PIN:-none})"
    "$PIP" uninstall -y torchaudio
  fi
fi

  TORCH_CONSTRAINTS="$VENV_DIR/kaine-torch-constraints.txt"
  pinned=$(write_torch_constraints "$TORCH_CONSTRAINTS")
  echo "==> pinned torch stack: $pinned"

  echo "==> installing the rest of KAINE (editable, with test deps and extras: $EXTRAS)"
  "$PIP" install --quiet -c "$TORCH_CONSTRAINTS" -e ".[test,$EXTRAS]"
else
  echo "==> installing the rest of KAINE (editable, with test deps and extras: $EXTRAS) (no torch)"
  "$PIP" install --quiet -e ".[test,$EXTRAS]"
fi

# Audio-stack coherence: a pre-existing torchaudio on any flavor must follow
# the selected torch stack when --research is not set.
if [[ "$NEED_TORCHAUDIO" -eq 1 ]]; then
  _install_torchaudio coherence "$INDEX_URL" "$TA_PIN" "$TORCH_CONSTRAINTS" ""
  pinned=$(write_torch_constraints "$TORCH_CONSTRAINTS")
  echo "==> pinned torch stack: $pinned"
fi

# --research: ALSO provision the perception extras (audio+vision incl. PyAV) so
# the reproducible perception feed can decode playlist media (cv2 video + av
# audio) on a fresh research machine. The default install stays lean.
if [[ "$NEED_TORCH" -eq 1 ]]; then
  if [[ "$RESEARCH" -eq 1 ]]; then
    _install_torchaudio research "$INDEX_URL" "$TA_PIN" "$TORCH_CONSTRAINTS" "$FORCE_REINSTALL_FLAG"
    pinned=$(write_torch_constraints "$TORCH_CONSTRAINTS")
    echo "==> pinned torch stack: $pinned"
    echo "==> [--research] installing perception extras: pip install -c $TORCH_CONSTRAINTS -e .[perception]"
    echo "    (audio: sounddevice, webrtcvad, funasr, librosa, av;  vision: opencv-python-headless)"
    "$PIP" install -c "$TORCH_CONSTRAINTS" -e ".[perception]"
    echo "==> [--research] perception extras installed (playlist audio/video decode ready)"
  fi
fi

if [[ "$NEED_TORCH" -eq 1 ]]; then
  echo "==> verifying"
  "$PY" - <<'PY'
import torch
from kaine.hardware import describe_host
import json
print("torch", torch.__version__)
print("cuda.is_available", torch.cuda.is_available())
print(json.dumps(describe_host(), indent=2, default=str))
PY

  "$PY" - <<'PY'
import sys
from kaine.torch_stack import check_torch_stack
problems = check_torch_stack()
for p in problems:
    print("TORCH STACK MISMATCH:", p, file=sys.stderr)
sys.exit(1 if problems else 0)
PY
else
  echo "==> verifying extras support (no torch requested)"
  "$PY" - "$PWD" <<'PY'
import os, sys
from kaine.config import load_runtime_config
from kaine.extras import check, format_missing
# The repository root: config/kaine.toml, profiles and the operator overlay
# resolve from here exactly as they do at boot. A config that cannot load fails
# the verification; it is never replaced by an empty one.
os.chdir(sys.argv[1])
config = load_runtime_config()
missing = check(config)
errors = [m for m in missing if m.severity == "error"]
if errors:
    print(format_missing(missing), file=sys.stderr)
    sys.exit(1)
for m in missing:
    print(f"note: {m.module} can use {m.import_name!r} (extra {m.extra!r}); not installed")
print("extras support OK")
PY
fi

echo "==> install complete"

# GPU trainer note: this script sets up the KAINE runtime venv only. The
# voice-alignment GPU trainer (Unsloth Studio on NVIDIA, unsloth-core on AMD)
# is a SEPARATE environment — never install it into the KAINE runtime venv.
# For Qwen3.5 support the trainer env also requires transformers v5 (Unsloth
# Studio ships 4.x by default). See docs/hardware.md#qwen35-trainer-prerequisites
# for the upgrade command and the mainline-GGUF conversion requirement.

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
      echo "==> skipped. Run it later with: $VENV_DIR/bin/python -m kaine.setup" ;;
  esac
else
  echo "==> run the first-run wizard with: $VENV_DIR/bin/python -m kaine.setup"
fi
