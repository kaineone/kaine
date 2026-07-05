## ADDED Requirements

### Requirement: Install script picks the PyTorch wheel by host probe
The repository SHALL ship an install script at `scripts/install.sh`
(Bash) and `scripts/install.py` (Python equivalent) that detects
whether the host has a usable NVIDIA driver via `nvidia-smi` and
picks the PyTorch wheel index URL accordingly: a CUDA index for
NVIDIA hosts, the CPU index otherwise. The script SHALL install
PyTorch first from the chosen index, then run `pip install -e .[test]`
to install the rest of KAINE.

#### Scenario: NVIDIA host installs CUDA wheels
- **WHEN** an operator runs `bash scripts/install.sh` on a host where
  `nvidia-smi` exists and returns success
- **THEN** the script invokes `pip install --index-url
  https://download.pytorch.org/whl/cu128 torch>=2.5,<3` (or the
  fallback URL for older drivers) in the venv

#### Scenario: CPU-only host installs CPU wheels
- **WHEN** an operator runs `bash scripts/install.sh` on a host where
  `nvidia-smi` is absent
- **THEN** the script invokes `pip install --index-url
  https://download.pytorch.org/whl/cpu torch>=2.5,<3` in the venv

#### Scenario: Idempotent re-run skips already-installed torch
- **WHEN** the script is run twice in succession with no change in
  hardware
- **THEN** the second run notes that torch is already installed at
  the right flavor and skips the torch install step, but still runs
  `pip install -e .[test]` to pick up any pyproject changes

### Requirement: Runtime device selection helper
The `kaine.hardware` module SHALL expose `detect_device() -> str`
returning `"cuda"`, `"mps"`, or `"cpu"` based on what PyTorch reports
available. The function SHALL prefer CUDA over MPS over CPU.

#### Scenario: CUDA available returns cuda
- **WHEN** `torch.cuda.is_available()` returns True
- **THEN** `detect_device()` returns `"cuda"`

#### Scenario: No accelerator returns cpu
- **WHEN** neither CUDA nor MPS is available
- **THEN** `detect_device()` returns `"cpu"`

### Requirement: Module-level device override and env-var override
`kaine.hardware` SHALL expose `select_device(preferred: str | None) -> str`
that accepts a per-module preferred device (e.g. `"cpu"` for the
<100K-parameter Chronos network even on a CUDA host) and SHALL honor
the `KAINE_FORCE_DEVICE` environment variable as the highest priority
override.

#### Scenario: Preferred argument honored
- **WHEN** a module calls `select_device("cpu")` on a CUDA host
- **THEN** the returned value is `"cpu"`

#### Scenario: Env var overrides everything
- **WHEN** `KAINE_FORCE_DEVICE=cpu` is set and `select_device("cuda")`
  is called on a CUDA host
- **THEN** the returned value is `"cpu"`

### Requirement: Structured host description for diagnostics
`kaine.hardware` SHALL expose `describe_host() -> dict[str, Any]`
returning at minimum: `device` (the auto-detected device),
`cuda_available` (bool), `mps_available` (bool), `gpu_count` (int),
`gpu_names` (list[str], may be empty), `torch_version` (str). The dict
SHALL be JSON-serializable so Soma can include it in its `soma.report`
payloads and Nexus can render it in diagnostics.

#### Scenario: NVIDIA host shows GPU names
- **WHEN** `describe_host()` is called on a host with two NVIDIA GPUs
- **THEN** the returned dict has `gpu_count == 2` and `gpu_names`
  containing both device names

#### Scenario: CPU-only host yields empty gpu_names
- **WHEN** `describe_host()` is called on a host with no GPU
- **THEN** `gpu_count == 0`, `gpu_names == []`, `device == "cpu"`,
  `cuda_available == False`

### Requirement: torch dependency declared without index pin
`pyproject.toml` SHALL declare `torch>=2.5,<3` and `ncps>=1.0,<2` under
`[project.dependencies]` with no index URL in the declaration. The
install script is the only place the wheel source is chosen.

#### Scenario: pyproject.toml stays portable
- **WHEN** an operator inspects `pyproject.toml`
- **THEN** the `torch` entry does not embed a PyTorch index URL or a
  hardware-specific marker
