## Why

KAINE's hardware story is pinned to the maintainer's exact personal rig — specific
GPU models and VRAM, a named CPU and RAM size, and personal host names / a literal
Tailscale IP scattered through the docs. That makes it hard for anyone else to run
the system or experiment with it. At the same time the device abstraction
(`kaine.hardware`) and the installer only know NVIDIA CUDA and CPU, even though the
runtime helpers already half-support Apple MPS. Operators on AMD or Intel GPUs, or
on Apple Silicon, have no first-class path.

We want others to be able to run and experiment. So: generalize the documented
hardware to generic, role-based requirements; add real multi-vendor GPU support
*now* (Apple MPS finished, AMD ROCm and Intel Arc/XPU added) in the one place that
already centralizes device selection; and record — clearly marked as
post-research roadmap — the future directions for distributed computing and for
smaller / upcycled hardware.

## What Changes

- `kaine.hardware` SHALL support Intel XPU (`xpu` / `xpu:N`) as a first-class
  device string alongside the existing `cuda` / `cuda:N`, `mps`, and `cpu`, and
  SHALL recognize AMD ROCm builds of PyTorch (which report through the CUDA device
  API, distinguished by a HIP build) and surface the backend in diagnostics.
  Selection stays graceful: an unavailable accelerator falls back with a warning,
  never a crash; `KAINE_FORCE_DEVICE` still overrides everything.
- `describe_host()` SHALL gain `backend`, `hip_version`, and `xpu_*` keys without
  removing any existing key (existing keys are a spec contract consumed by Soma
  and Nexus).
- The installer (`scripts/install.sh` and `scripts/install.py`) SHALL detect AMD
  (ROCm) and Intel (XPU) GPUs and Apple Silicon in addition to NVIDIA, pick the
  matching PyTorch wheel index (ROCm / XPU / default-wheel-for-MPS / CUDA / CPU),
  expose `--rocm` / `--xpu` / `--mps` flags alongside `--cuda` / `--cpu`, and keep
  the idempotent re-run check across all flavors.
- Documentation SHALL replace exact-rig specifications with generic, role-based
  requirements (primary GPU VRAM tier, secondary GPU tier, CPU/RAM minimum, which
  components are CPU-pinned and why), remove personal host names and the literal
  Tailscale IP in favor of operator-substitutable placeholders, and add a GPU /
  accelerator backend support matrix.
- Documentation SHALL add a clearly-marked **roadmap** section (most items gated
  on post-research validation that the system produces cognitive behaviour):
  distributed computing across peer hosts (cross-referencing
  `openspec/changes/distributed-substrate/`) and reduced-footprint operation on
  single-board computers, upcycled smartphones, and other architectures such as
  RISC-V (cross-referencing `openspec/changes/portability-tiers/`). The
  brand-specific naming in those existing roadmap changes SHALL be generalized to
  capability/RAM tiers ("single-board computer (SBC)").
- The Speaches STT CPU + `medium.en` guidance and the Speaches `:8000/v1/models`
  endpoint are unchanged.

## Capabilities

### New Capabilities

<!-- none -->

### Modified Capabilities

- `dynamic-hardware`: extend the runtime device-selection helper to add Intel XPU
  as a device string and to recognize AMD ROCm builds; extend `describe_host()`
  with backend/HIP/XPU keys; extend the install-script host probe to detect AMD,
  Intel, and Apple Silicon and pick the matching wheel index with new force flags.

## Impact

- **Code**: `kaine/hardware.py` (XPU device string, ROCm backend label, extended
  `describe_host`), `scripts/install.sh` + `scripts/install.py` (multi-vendor
  probe + wheel index + flags).
- **Docs**: `docs/tech-choices.md`, `docs/getting-started.md`, `docs/KAINE_Paper.md`,
  `docs/CONNECTION_GUIDE.md`, `docs/modules/mundus.md`, plus comment-only edits in
  `config/kaine.toml`, `kaine/modules/hypnos/voice_alignment.py`, and
  `kaine/modules/lingua/ABLITERATION.md`; brand-name generalization in
  `openspec/changes/portability-tiers/` and `openspec/changes/distributed-substrate/`.
- **Tests**: `tests/test_hardware.py` gains mocked-backend coverage for XPU
  detection/selection/fallback and ROCm backend labeling (no non-NVIDIA hardware
  required).
- **Operator**: non-NVIDIA backends are best-effort and community-testable; the
  installer auto-detects, with force flags as the escape hatch.
