## MODIFIED Requirements

### Requirement: Install script picks the PyTorch wheel by host probe
The repository SHALL ship an install script at `scripts/install.sh` (Bash) and
`scripts/install.py` (Python equivalent) that detects the host's accelerator and
picks the PyTorch wheel index URL accordingly. Detection order when no flavor is
forced SHALL be: NVIDIA (a usable driver via `nvidia-smi`) → AMD ROCm
(`rocm-smi` present or `/opt/rocm` exists) → Intel XPU (`xpu-smi` or `sycl-ls`
present) → Apple Silicon (macOS on `arm64`) → CPU. The chosen flavor SHALL map to
a wheel source: NVIDIA → a CUDA index, AMD → a ROCm index, Intel → an XPU index,
CPU → the CPU index; Apple Silicon SHALL install the default PyPI wheel (which
bundles the MPS backend) with no `--index-url`. The script SHALL accept force
flags `--cpu`, `--cuda`, `--rocm`, `--xpu`, and `--mps`. The script SHALL install
PyTorch first from the chosen source, then run `pip install -e .[test]` to install
the rest of KAINE.

#### Scenario: NVIDIA host installs CUDA wheels
- **WHEN** an operator runs `bash scripts/install.sh` on a host where
  `nvidia-smi` exists and returns success
- **THEN** the script invokes `pip install --index-url
  https://download.pytorch.org/whl/cu128 torch>=2.5,<3` (or the
  fallback URL for older drivers) in the venv

#### Scenario: CPU-only host installs CPU wheels
- **WHEN** an operator runs `bash scripts/install.sh` on a host where
  `nvidia-smi` is absent and no AMD/Intel/Apple accelerator is detected
- **THEN** the script invokes `pip install --index-url
  https://download.pytorch.org/whl/cpu torch>=2.5,<3` in the venv

#### Scenario: AMD host installs ROCm wheels
- **WHEN** an operator runs `bash scripts/install.sh --rocm`, or on a host where
  `rocm-smi` is present (or `/opt/rocm` exists) and no NVIDIA driver is detected
- **THEN** the script invokes `pip install` from a ROCm wheel index
  (`https://download.pytorch.org/whl/rocm6.2`) in the venv

#### Scenario: Intel host installs XPU wheels
- **WHEN** an operator runs `bash scripts/install.sh --xpu`, or on a host where
  `xpu-smi`/`sycl-ls` is present and no NVIDIA or AMD accelerator is detected
- **THEN** the script invokes `pip install` from the XPU wheel index
  (`https://download.pytorch.org/whl/xpu`) in the venv

#### Scenario: Apple Silicon installs the default wheel for MPS
- **WHEN** an operator runs `bash scripts/install.sh --mps`, or on macOS `arm64`
  with no other accelerator forced
- **THEN** the script installs `torch>=2.5,<3` from the default PyPI index with no
  `--index-url`, because the MPS backend ships in the standard macOS wheel

#### Scenario: Idempotent re-run skips already-installed torch
- **WHEN** the script is run twice in succession with no change in
  hardware
- **THEN** the second run notes that torch is already installed at
  the right flavor (recognizing cuda, rocm, xpu, mps, or cpu) and skips the torch
  install step, but still runs `pip install -e .[test]` to pick up any pyproject
  changes

### Requirement: Runtime device selection helper
The `kaine.hardware` module SHALL expose `detect_device() -> str` returning
`"cuda"`, `"xpu"`, `"mps"`, or `"cpu"` based on what PyTorch reports available.
The function SHALL prefer CUDA over XPU over MPS over CPU. AMD ROCm builds of
PyTorch report through the CUDA device API and therefore resolve to `"cuda"`;
they are distinguished from NVIDIA only in diagnostics (`describe_host`), not in
the device string.

#### Scenario: CUDA available returns cuda
- **WHEN** `torch.cuda.is_available()` returns True
- **THEN** `detect_device()` returns `"cuda"`

#### Scenario: Intel XPU available returns xpu
- **WHEN** CUDA is unavailable and `torch.xpu.is_available()` returns True
- **THEN** `detect_device()` returns `"xpu"`

#### Scenario: No accelerator returns cpu
- **WHEN** none of CUDA, XPU, or MPS is available
- **THEN** `detect_device()` returns `"cpu"`

### Requirement: Module-level device override and env-var override
`kaine.hardware` SHALL expose `select_device(preferred: str | None) -> str`
that accepts a per-module preferred device (e.g. `"cpu"` for the
<100K-parameter Chronos network even on a CUDA host) and SHALL honor
the `KAINE_FORCE_DEVICE` environment variable as the highest priority
override. Preferred indexed accelerator strings (`cuda:N`, `xpu:N`) SHALL be
validated against the available device count: `select_device` SHALL raise on an
out-of-range index, while `resolve_device` SHALL fall back with a warning rather
than raise.

#### Scenario: Preferred argument honored
- **WHEN** a module calls `select_device("cpu")` on a CUDA host
- **THEN** the returned value is `"cpu"`

#### Scenario: Env var overrides everything
- **WHEN** `KAINE_FORCE_DEVICE=cpu` is set and `select_device("cuda")`
  is called on a CUDA host
- **THEN** the returned value is `"cpu"`

#### Scenario: Out-of-range XPU index falls back under resolve_device
- **WHEN** `resolve_device("xpu:3")` is called on a host with fewer than four XPU
  devices
- **THEN** the function returns a valid available device (not `"xpu:3"`) and logs
  a warning rather than raising

### Requirement: Structured host description for diagnostics
`kaine.hardware` SHALL expose `describe_host() -> dict[str, Any]`
returning at minimum: `device` (the auto-detected device),
`cuda_available` (bool), `mps_available` (bool), `gpu_count` (int),
`gpu_names` (list[str], may be empty), `torch_version` (str), plus
multi-vendor fields: `backend` (one of `"rocm"`, `"cuda"`, `"xpu"`, `"mps"`,
`"cpu"`), `hip_version` (str or null; non-null on AMD ROCm builds),
`xpu_available` (bool), `xpu_count` (int), and `xpu_names` (list[str], may be
empty). The dict SHALL be JSON-serializable so Soma can include it in its
`soma.report` payloads and Nexus can render it in diagnostics, and SHALL NOT raise
when a backend probe fails.

#### Scenario: NVIDIA host shows GPU names
- **WHEN** `describe_host()` is called on a host with two NVIDIA GPUs
- **THEN** the returned dict has `gpu_count == 2` and `gpu_names`
  containing both device names, and `backend == "cuda"`

#### Scenario: AMD ROCm host reports the rocm backend
- **WHEN** `describe_host()` is called on a host running a ROCm build of PyTorch
  (`torch.version.hip` is set and `torch.cuda.is_available()` is True)
- **THEN** the returned dict has `backend == "rocm"` and a non-null `hip_version`

#### Scenario: CPU-only host yields empty gpu_names
- **WHEN** `describe_host()` is called on a host with no GPU
- **THEN** `gpu_count == 0`, `gpu_names == []`, `device == "cpu"`,
  `cuda_available == False`, and `backend == "cpu"`

## ADDED Requirements

### Requirement: Intel XPU accelerator support
`kaine.hardware` SHALL treat `"xpu"` and `"xpu:N"` as first-class device strings
gated by `torch.xpu.is_available()` and counted by `torch.xpu.device_count()`,
exposing `available_xpu_devices() -> list[str]` mirroring the CUDA helper. All XPU
probing SHALL be fully guarded so that a host whose PyTorch build lacks the XPU
module behaves exactly as before (XPU simply reports unavailable; no exception
escapes).

#### Scenario: XPU device string validates and selects
- **WHEN** `select_device("xpu")` is called on a host where `torch.xpu` reports
  one or more devices available
- **THEN** the returned value is `"xpu"`

#### Scenario: Missing XPU module does not crash
- **WHEN** `detect_device()` or `describe_host()` runs on a PyTorch build with no
  `torch.xpu` attribute
- **THEN** no exception is raised and XPU is reported as unavailable
  (`xpu_available == False`, `xpu_count == 0`)
