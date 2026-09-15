# dynamic-hardware Specification

## Purpose
TBD - created by archiving change dynamic-torch-install. Update Purpose after archive.

## Requirements

### Requirement: Install script picks the PyTorch wheel by host probe
The repository SHALL ship an install script at `scripts/install.sh` (Bash) and
`scripts/install.py` (Python equivalent) that detects the host's accelerator and
picks the PyTorch wheel index URL accordingly. Detection order when no flavor is
forced SHALL be: NVIDIA (a usable driver via `nvidia-smi`) → AMD ROCm
(`rocm-smi` present or `/opt/rocm` exists) → Intel XPU (`xpu-smi` or `sycl-ls`
present) → Apple Silicon (macOS on `arm64`) → CPU. The chosen flavor SHALL map
to a wheel source: NVIDIA → a CUDA index resolved from the host probe as
described below, AMD → a ROCm index, Intel → an XPU index, CPU → the CPU index;
Apple Silicon SHALL install the default PyPI wheel (which bundles the MPS
backend) with no `--index-url`. The script SHALL install PyTorch first from the
chosen source, then run `pip install -e .[test]` to install the rest of KAINE.

The NVIDIA flavor SHALL NOT map to a single fixed CUDA index. When the NVIDIA
flavor is selected (auto-detected or forced with `--cuda`), the script SHALL
probe the host's CPU architecture (e.g. `uname -m`), the driver's maximum
supported CUDA version (from the `nvidia-smi` report), the GPU's compute
capability (e.g. `nvidia-smi --query-gpu=compute_cap`), and whether the GPU has
unified memory (an integrated GPU sharing system RAM, e.g. NVIDIA Tegra/Jetson
parts). It SHALL resolve the CUDA wheel index by looking these probes up in a
documented, ordered fallback table shipped in the repository and shared by both
implementations, selecting the first entry that (a) targets a CUDA version no
newer than the driver supports, (b) ships kernels — or PTX forward
compatibility — for the probed compute capability on the probed architecture,
and (c) matches the unified-memory classification; a final fallback entry SHALL
always match so resolution cannot fail. The script SHALL log the probe results
and the resolved index (or operator override) before installing torch.

The script SHALL accept force flags `--cpu`, `--cuda`, `--rocm`, `--xpu`, and
`--mps` with their exact existing semantics, plus a new `--index-url <URL>`
override: when `--index-url` is given and the CUDA flavor is selected, the
script SHALL use that URL verbatim in place of the table-resolved index.
`--index-url` SHALL NOT change which flavor is detected or forced. The Bash and
Python implementations SHALL agree on detection order, table resolution, and
flag semantics.

#### Scenario: NVIDIA host installs CUDA wheels
- **WHEN** an operator runs `bash scripts/install.sh` on a dual-GPU x86_64
  workstation where `nvidia-smi` exists and returns success, the driver
  supports CUDA 12.8, and the GPUs are discrete with compute capabilities
  covered by the newest table entry
- **THEN** the script resolves the CUDA index from the probe table (not a
  hardcoded constant) and invokes `pip install --index-url
  https://download.pytorch.org/whl/cu128 torch>=2.5,<3` in the venv

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

#### Scenario: aarch64 unified-memory host avoids the SBSA-only index
- **WHEN** an operator runs `bash scripts/install.sh` on an aarch64 host with a
  unified-memory Tegra/Jetson GPU whose compute capability is not covered by
  the SBSA sm_90/sm_100 builds served by the cu128 index, and `nvidia-smi`
  succeeds
- **THEN** the table resolution does not select the cu128 index; the script
  installs from the table entry whose aarch64 wheels ship kernels for the
  probed compute capability (e.g. a Jetson-specific wheel index), so the
  installed torch can launch kernels on the device instead of failing with
  "no kernel image is available for execution on the device"

#### Scenario: Newer driver resolves a newer CUDA index
- **WHEN** the probed driver reports support for CUDA 13.x and the GPUs'
  compute capabilities are covered by a cu13x table entry
- **THEN** the script resolves a cu13x wheel index (e.g.
  `https://download.pytorch.org/whl/cu130`) from the table and installs from
  it, rather than installing cu128 wheels against a newer driver

#### Scenario: Older driver falls back down the ordered table
- **WHEN** the probed driver's maximum supported CUDA version is older than the
  newest table entry (e.g. a driver that supports only CUDA 11.8)
- **THEN** the script selects the newest table entry whose CUDA version the
  driver still supports (e.g. the cu118 index) and never an index newer than
  the driver supports

#### Scenario: Operator override with --index-url
- **WHEN** an operator runs `bash scripts/install.sh --cuda --index-url
  https://download.pytorch.org/whl/cu126` on an NVIDIA host
- **THEN** the script invokes `pip install --index-url
  https://download.pytorch.org/whl/cu126 torch>=2.5,<3` in the venv, bypassing
  the table resolution, while flavor detection and the other force flags keep
  their existing semantics

#### Scenario: Probe results and resolved index are logged
- **WHEN** the script selects the NVIDIA flavor, whether auto-detected or
  forced with `--cuda`
- **THEN** it logs the probed architecture, driver CUDA version, compute
  capability, unified-memory classification, and the wheel index it will use
  (table-resolved or operator override) before installing torch

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
empty).

`describe_host()` SHALL additionally classify the accelerator's memory and
report per-pool figures under a `memory` key. `memory.kind` SHALL be one of
`"discrete"` (a separate VRAM pool exists), `"unified"` (the accelerator shares
system RAM, as on NVIDIA Tegra/Jetson, AMD APUs, and Apple Silicon), or
`"unknown"` (classification or measurement failed). `memory.pools` SHALL be a
list of pool entries, each with `name` (`"vram"` for the discrete VRAM pool,
`"system"` for system RAM), `total_bytes` and `free_bytes` (each a non-negative
int or `null`), and `provenance` (a short string identifying the measurement
source, e.g. `"nvml"`, `"torch"`, `"os"`, or `"unknown"` when no source
succeeded); a `null` figure with provenance `"unknown"` is the explicit marker
for an unmeasurable value. On discrete hosts the pools SHALL include a
`"vram"` pool with measured figures and their provenance. On unified-memory
hosts the pools SHALL include a `"system"` pool with figures measured from the
OS, and any accelerator pool entry SHALL carry `null` figures with provenance
`"unknown"` (NVML typically reports "Not Supported") rather than zero, so such
hosts are never reported as having missing or zero usable memory. On hosts with
no accelerator, `memory.kind` SHALL be `"unknown"` with an empty pool list.
The `memory` block SHALL give the `gpu-preflight` gate enough information to
distinguish known-discrete, known-unified, and unknown memory states.

The dict SHALL be JSON-serializable so Soma can include it in its
`soma.report` payloads and Nexus can render it in diagnostics, and SHALL NOT
raise when a backend probe or a memory probe fails; a failing probe SHALL
degrade to the explicit unknown markers above instead of an exception.

#### Scenario: NVIDIA host shows GPU names
- **WHEN** `describe_host()` is called on a host with two discrete NVIDIA GPUs
- **THEN** the returned dict has `gpu_count == 2` and `gpu_names`
  containing both device names, `backend == "cuda"`, and `memory.kind ==
  "discrete"` with a `"vram"` pool carrying non-null `total_bytes` and
  `free_bytes` plus a provenance string

#### Scenario: AMD ROCm host reports the rocm backend
- **WHEN** `describe_host()` is called on a host running a ROCm build of PyTorch
  (`torch.version.hip` is set and `torch.cuda.is_available()` is True)
- **THEN** the returned dict has `backend == "rocm"` and a non-null `hip_version`

#### Scenario: CPU-only host yields empty gpu_names
- **WHEN** `describe_host()` is called on a host with no GPU
- **THEN** `gpu_count == 0`, `gpu_names == []`, `device == "cpu"`,
  `cuda_available == False`, `backend == "cpu"`, and `memory.kind == "unknown"`
  with an empty pool list

#### Scenario: Unified-memory host reports the shared system pool
- **WHEN** `describe_host()` is called on a Tegra/Jetson host (or an AMD APU or
  Apple Silicon Mac) where the accelerator shares system RAM and NVML reports
  "Not Supported" for memory
- **THEN** the returned dict has `memory.kind == "unified"`, any accelerator
  pool entry has `null` `total_bytes`/`free_bytes` with provenance `"unknown"`,
  and a `"system"` pool carries non-null figures with an OS provenance, so the
  host is not reported as having zero or missing usable memory

#### Scenario: Apple Silicon host reports unified memory under MPS
- **WHEN** `describe_host()` is called on a macOS `arm64` host where
  `mps_available` is True
- **THEN** the returned dict has `backend == "mps"` and `memory.kind ==
  "unified"` with a `"system"` pool measured from the OS

#### Scenario: Memory probe failure degrades to explicit unknowns
- **WHEN** every memory measurement source fails on a host with a GPU (e.g.
  NVML raises and torch memory queries are unavailable)
- **THEN** `describe_host()` does not raise, returns `memory.kind == "unknown"`
  with `null` figures and provenance `"unknown"` for the affected pools, and
  the returned dict is still JSON-serializable

### Requirement: torch dependency declared without index pin
`pyproject.toml` SHALL declare `torch>=2.5,<3` and `ncps>=1.0,<2` under
`[project.dependencies]` with no index URL in the declaration. The
install script is the only place the wheel source is chosen.

#### Scenario: pyproject.toml stays portable
- **WHEN** an operator inspects `pyproject.toml`
- **THEN** the `torch` entry does not embed a PyTorch index URL or a
  hardware-specific marker

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
