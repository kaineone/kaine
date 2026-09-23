## MODIFIED Requirements

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
backend) with no `--index-url`. The script SHALL install the exact torch version (and matching companions) resolved as described below from the
chosen source, pin it in the torch constraints file, then install the rest of KAINE under those constraints.

The NVIDIA flavor SHALL NOT map to a single fixed CUDA index. When the NVIDIA
flavor is selected (auto-detected or forced with `--cuda`), the script SHALL
probe the host's CPU architecture (e.g. `uname -m`), the driver's maximum
supported CUDA version (from the `nvidia-smi` report), the GPU's compute
capability (e.g. `nvidia-smi --query-gpu=compute_cap`), and whether the GPU has
unified memory (an integrated GPU sharing system RAM, e.g. NVIDIA Tegra/Jetson
parts). It SHALL resolve the CUDA wheel index by looking these probes up in a
documented, ordered fallback table shipped in the repository and shared by both
implementations, selecting the first entry that (a) targets a CUDA version no
newer than the driver supports, (b) publishes a torch version satisfying the
full torch specifier in `pyproject.toml`, (c) for the newest such version, ships
kernels — exact SASS, same-major SASS, or PTX forward compatibility — for the
probed compute capability on the probed architecture, and (d) matches the
unified-memory classification; the resolver SHALL output that exact torch version; a final fallback entry SHALL
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
  https://download.pytorch.org/whl/cu128 torch==2.11.0` (the newest in-range torch on that index) in the venv

#### Scenario: CPU-only host installs CPU wheels
- **WHEN** an operator runs `bash scripts/install.sh` on a host where
  `nvidia-smi` is absent and no AMD/Intel/Apple accelerator is detected
- **THEN** the script invokes `pip install --index-url
  https://download.pytorch.org/whl/cpu` with the exact newest in-range torch in the venv

#### Scenario: AMD host installs ROCm wheels
- **WHEN** an operator runs `bash scripts/install.sh --rocm`, or on a host where
  `rocm-smi` is present (or `/opt/rocm` exists) and no NVIDIA driver is detected
- **THEN** the resolver probes the ROCm version and gfx target and the script
  invokes `pip install` from the newest ROCm wheel index that carries an in-range
  torch for that stack, or refuses with a message naming the ROCm requirement

#### Scenario: Intel host installs XPU wheels
- **WHEN** an operator runs `bash scripts/install.sh --xpu`, or on a host where
  `xpu-smi`/`sycl-ls` is present and no NVIDIA or AMD accelerator is detected
- **THEN** the script invokes `pip install` from the XPU wheel index
  (`https://download.pytorch.org/whl/xpu`) in the venv

#### Scenario: Apple Silicon installs the default wheel for MPS
- **WHEN** an operator runs `bash scripts/install.sh --mps`, or on macOS `arm64`
  with no other accelerator forced
- **THEN** the script installs the exact newest in-range torch from the default PyPI index with no
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
  unified-memory Tegra/Jetson GPU whose compute capability is not covered by the
  in-range torch on an index, even under the same-major SASS rule and the
  recorded unified-host architecture list
- **THEN** the table resolution does not select that index, so the installed
  torch never fails with "no kernel image is available for execution on the
  device"

#### Scenario: aarch64 unified-memory host on JetPack 7
- **WHEN** an operator runs `bash scripts/install.sh` on an aarch64 host with a
  unified-memory Jetson Orin GPU (sm_87) whose driver reports CUDA 13.x
- **THEN** the resolver selects the newest cu13x index carrying an in-range torch
  under the unified-host exception backed by the wheel's recorded architecture
  list, the installer runs the fp16/bf16 GPU-versus-CPU self-test, and it keeps
  the GPU wheels only if the self-test passes (otherwise it installs CPU wheels
  and reports why)

#### Scenario: aarch64 unified-memory host on JetPack 6
- **WHEN** the driver on a unified-memory Jetson reports CUDA 12.x
- **THEN** the resolver selects the CPU index and the note names the Python 3.12
  requirement and the manual `--index-url` override

#### Scenario: Newer driver resolves a newer CUDA index
- **WHEN** the probed driver reports support for CUDA 13.x and the GPUs'
  compute capabilities are covered by the in-range torch on a cu13x index
- **THEN** the script resolves that cu13x wheel index (e.g.
  `https://download.pytorch.org/whl/cu130`) and installs its newest in-range
  torch, rather than installing older CUDA builds against a newer driver

#### Scenario: Older driver falls back down the ordered table
- **WHEN** the probed driver's maximum supported CUDA version is older than the
  newest table entry (e.g. a driver that supports only CUDA 11.8)
- **THEN** the script selects the newest table entry whose CUDA version the
  driver still supports and that carries an in-range torch covering the GPU,
  never an index newer than the driver supports, and selects CPU with a warning
  naming the torch range and the driver when no such entry exists

#### Scenario: Operator override with --index-url
- **WHEN** an operator runs `bash scripts/install.sh --cuda --index-url
  https://download.pytorch.org/whl/cu126` on an NVIDIA host
- **THEN** the script invokes `pip install --index-url
  https://download.pytorch.org/whl/cu126` with the newest in-range torch in the venv,
  bypassing the table resolution, while flavor detection and the other force flags keep
  their existing semantics

#### Scenario: Probe results and resolved index are logged
- **WHEN** the script selects the NVIDIA flavor, whether auto-detected or
  forced with `--cuda`
- **THEN** it logs the probed architecture, driver CUDA version, compute
  capability, unified-memory classification, and the wheel index it will use
  (table-resolved or operator override) before installing torch

### Requirement: torch dependency declared without index pin
`pyproject.toml` SHALL declare torch as a tested version range (currently
`torch>=2.9.1,<2.15`) and `ncps>=1.0,<2` under `[project.dependencies]` with no
index URL in the declaration. The install script is the only place the wheel
source and exact version are chosen. Automated dependency updates SHALL NOT
change the torch, torchvision or torchaudio range; the range changes only
through a change whose CI passes the offline suite at both ends of the new range
on the CPU index and whose accelerator smoke tests are recorded.

#### Scenario: pyproject.toml stays portable
- **WHEN** an operator inspects `pyproject.toml`
- **THEN** the `torch` entry is a bounded tested range and does not embed a
  PyTorch index URL or a hardware-specific marker

#### Scenario: Dependabot proposes a torch bump
- **WHEN** a new torch release is published
- **THEN** no automated pull request changes the torch range
