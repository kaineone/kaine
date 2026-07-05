## Context

PyTorch is the only Python dependency in the KAINE plan whose wheel
choice depends on host hardware (and matters enough — multi-GB
difference — that picking wrong is a real cost). Other future
hardware-sensitive deps (`faster-whisper`'s CTranslate2 backend,
`unsloth`, `xformers`) follow the same pattern and will reuse the same
install script.

Constraints:
- All-local: the install script downloads wheels from
  `download.pytorch.org`, which is one-time setup, not a runtime
  dependency. Once installed, no runtime network calls.
- Portable: must work on Linux Mint (Bash), generic Linux distros
  (Bash), and reasonably on macOS (which the Python variant
  supports). Windows is out of scope.
- Reproducible: the same script run on the same hardware picks the
  same wheels.

Stakeholders: every future phase that touches PyTorch (2.2 Chronos,
2.3 Topos, 6 Hypnos), plus the operator who clones the repo on a new
host.

## Goals / Non-Goals

**Goals:**
- One-command install for fresh clones on CPU-only and NVIDIA hosts.
- PyTorch wheel choice driven by host probe, not by the operator
  choosing an extras flag.
- Runtime helper `detect_device()` in `kaine.hardware` for modules
  that need to pick where to put tensors.
- Clear failure messages when the detected configuration doesn't
  match what's available (e.g. NVIDIA driver too old for the wheel
  version).

**Non-Goals:**
- ROCm (AMD) and Apple Silicon (MPS) support, beyond stubs in the
  detection logic. Real support lands when KAINE actually runs on
  those hosts.
- A KAINE-specific PyTorch fork or wheel mirror. We use upstream
  PyTorch wheels from `download.pytorch.org`.
- Conda. Pip-only.

## Decisions

**Detect NVIDIA via `nvidia-smi`, not `nvcc`.** `nvidia-smi` ships with
the driver and is present on every NVIDIA host; `nvcc` ships with the
CUDA toolkit which is often not installed on inference-only boxes.
KAINE doesn't need `nvcc` — PyTorch wheels are precompiled.

**Pick `cu128` wheels by default for NVIDIA hosts.** Forward-compatible
with driver versions reporting CUDA 12.4+ (which covers any reasonably
recent driver), and matches what PyTorch ships as a stable index. On
hosts whose driver reports older CUDA (rare in 2026), the install
script falls back to `cu121` and prints a note. Older than that → CPU
wheels with a warning.

**Pin `torch>=2.5,<3`.** Major version 2 has been stable since 2023;
the `<3` upper bound lets us avoid the next major breaking change
without specifying a tight minor. Pin tightens later when Phase 6's
Unsloth training path is wired up.

**Install script does pip-only, against the project venv.** No system
pip, no Conda. The script assumes the venv is at `.venv/` (matching
Phase 1's setup); first run creates it if absent.

**Idempotent.** Re-running the script picks the same wheel index. If
the venv already has torch installed at the right version+flavor,
skip the torch install. Run `pip install -e .[test]` either way to
pick up any pyproject changes.

**Detection helper in `kaine.hardware`.** Three functions:
- `detect_device() -> str` returns `"cuda"`, `"mps"`, or `"cpu"`.
  Module code uses this rather than calling `torch.cuda.is_available()`
  directly, so future MPS / ROCm branches land in one place.
- `describe_host() -> dict[str, Any]` returns a structured snapshot
  for Soma (`gpu_count`, `gpu_names`, `cuda_available`, `mps_available`,
  `torch_version`). Soma's metrics dict can absorb this directly.
- `select_device(preferred: str | None) -> str` lets modules override
  (e.g. Chronos pins to "cpu" because its network is <100K params and
  doesn't benefit from GPU).

**The script is committed; the venv is not.** `.venv/` is gitignored.

## Risks / Trade-offs

- **PyTorch index URL hosts a moving target.** Wheel index URLs and
  available CUDA versions change. → Tested by the script on first
  run; failure prints the index URL and the command tried.
- **Driver/wheel mismatch on first install.** → Detection prints the
  chosen wheel and tells the operator what to do if the install
  fails (rerun with `--cpu` flag).
- **`nvidia-smi` may exist but fail (e.g. driver mismatched with NVML
  library).** → The script falls back to CPU wheels and prints a
  warning.
- **CPU torch wheels are still ~200 MB.** → Documented; unavoidable.

## Migration Plan

1. Operators who already have a working venv (this machine) re-run
   `scripts/install.sh`. The script detects NVIDIA, downloads cu128
   torch, installs over the existing venv. No need to nuke and start
   over.
2. Future fresh-clone operators use the script from the beginning.
3. The Phase 0 SETUP.md note about `pip install -e .[test]` is
   replaced with the script invocation.

Rollback: revert the commit. The system reverts to a working venv
without torch; Chronos won't start, but Phase 1 still passes its tests.

## Open Questions

- Whether to detect ROCm via `rocm-smi`. Deferring until we have a
  KAINE deployment on an AMD GPU host.
- Whether `select_device` should also accept an env-var override
  (`KAINE_FORCE_DEVICE=cpu`). Adding it now since it costs nothing
  and the operator may want to force CPU during debugging.
