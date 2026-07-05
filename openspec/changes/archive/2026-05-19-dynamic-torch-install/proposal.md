## Why

KAINE's design (`docs/kaine-paper.md` §6) explicitly spans hardware from
solar-powered microcontrollers to multi-GPU workstations. Phase 2.2
(Chronos) needs PyTorch for the CfC network; Phase 2.3 (Topos), Phase 6
(Hypnos training), and other later phases need it too. Picking either
CPU-only or CUDA-enabled PyTorch in `pyproject.toml` would break the
other half of the deployment spectrum.

The right answer is to detect the host at install time, pin the
appropriate wheel index for that host, and let runtime device selection
follow the same probe. This change introduces the install detection and
documents the pattern so every future GPU-flavored dep (faster-whisper,
xformers, unsloth) follows it.

The KAINE host we are building on right now is NVIDIA (RTX 4070 SUPER +
RTX 3070, driver 595.58.03, reports CUDA Version 13.2). On this machine
the install picks `cu128` wheels. On a CPU-only host the same script
picks the `cpu` index.

## What Changes

- Add `scripts/install.sh` (Bash) that:
  1. detects NVIDIA via `nvidia-smi`,
  2. picks the matching PyTorch index URL (`https://download.pytorch.org/whl/cu128`
     for NVIDIA hosts, `https://download.pytorch.org/whl/cpu` otherwise),
  3. runs `pip install --index-url <url> torch>=2.5,<3` in the project venv,
  4. runs `pip install -e .[test]` to install the rest of KAINE.
  Future variants for ROCm and Apple Silicon are stubbed but not enabled
  until those hosts are explicitly named.
- Add `scripts/install.py` as a portable Python equivalent for hosts
  without bash. Same detection logic via `shutil.which("nvidia-smi")`.
- Add `torch>=2.5,<3` and `ncps>=1.0,<2` to `pyproject.toml`
  `[project.dependencies]` with no index pin. The install script is
  what picks the wheel.
- Add `kaine/hardware.py` exposing `detect_device()` returning a torch
  device string (`"cuda"`, `"mps"`, or `"cpu"`) plus a `describe_host()`
  helper that returns a structured dict for Soma and Nexus diagnostics.
- Update `SETUP.md` §0 to point at `scripts/install.sh` as the canonical
  install command and replace any raw `pip install -e .[test]` lines.
- Update `DEPENDENCIES.md` adding `torch` and `ncps`, noting the dynamic
  install path.

## Capabilities

### New Capabilities

- `dynamic-hardware`: install-time and runtime hardware detection.
  Picks PyTorch wheel source on install; reports the chosen device at
  runtime so individual modules can decide what to put on it.

### Modified Capabilities

None — this is a project-level capability, not a modification of an
existing KAINE module.

## Impact

- **Repo:** adds `scripts/install.sh`, `scripts/install.py`, `kaine/hardware.py`,
  `tests/test_hardware.py`. Updates `pyproject.toml`, `SETUP.md`,
  `DEPENDENCIES.md`.
- **Operator action:** future fresh-clone operators run
  `bash scripts/install.sh` (or `python scripts/install.py`) instead of
  `pip install -e .[test]`. The existing venv on this machine gets
  refreshed by running the new script — it is idempotent.
- **Storage:** CUDA torch wheels are ~2 GB; CPU wheels are ~200 MB. The
  install script reports the chosen wheel size up front.
- **No runtime impact** on the cognitive cycle. Nothing boots.
