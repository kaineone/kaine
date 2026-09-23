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
backend) with no `--index-url`. The script SHALL install the exact torch version
(and matching companions) resolved as described below from the chosen source,
pin it in the torch constraints file, then install the rest of KAINE under those
constraints. For the cpu and xpu flavors the resolver SHALL select the newest
in-range torch that index publishes for the host architecture, with its recorded
torchvision and torchaudio companions (preferring a version with a torchaudio
companion when `torchaudio` is needed). When the recorded data covers the host
architecture for that flavor but has no in-range torch, or the flavor is xpu and
the architecture is not recorded, both installers SHALL refuse before installing
torch with a message naming the flavor and the host architecture. When the flavor
is cpu and the host architecture is not recorded at all (for example s390x), or
when the resolver cannot run, the installers SHALL install from the CPU index
within the tested range without an exact pin and print a warning naming the
reason; for xpu a resolver that cannot run SHALL be refused with a message saying
the resolver could not run. The mps flavor SHALL install torch within the tested range from the
default PyPI index without an exact pin, because no MPS wheel data is recorded. On re-run, the script SHALL classify the installed torch by its
build metadata (`torch.version.hip` → rocm, `torch.version.cuda` → cuda, an XPU
build → xpu, an MPS build on macOS arm64 → mps, else cpu), compare it with the
effective target flavor (cpu when the chosen index is the CPU index, for example
after a self-test fallback), and force-reinstall on a mismatch. A matching
flavor with a different pinned base version SHALL reinstall. On
`download.pytorch.org/whl/<tag>` indexes a local-tag mismatch SHALL force a
reinstall (untagged counts as cpu); for operator `--index-url` values that do not
point to `download.pytorch.org/whl/<tag>`, tag checks are skipped. When any
`torchaudio` wheel is installed and `--research` is not given, the script SHALL
pass `--need-torchaudio` to the resolver, replace a `torchaudio` that does not
match the resolved stack, keep one that matches it, and on the mps flavor, which
has no resolved `torchaudio` pin, reinstall `torchaudio` from the default PyPI
index under the torch constraints. If `torchaudio` is installed and the
chosen index publishes no `torchaudio` for the resolved torch version, both
installers SHALL refuse before installing torch.

The NVIDIA flavor SHALL NOT map to a single fixed CUDA index. When the NVIDIA
flavor is selected (auto-detected or forced with `--cuda`), the script SHALL
probe the host's CPU architecture (e.g. `uname -m`), the driver's maximum
supported CUDA version (first from the `nvidia-smi` header, then from NVML), the
GPU's compute capability (first from NVML, then `nvidia-smi
--query-gpu=compute_cap`, then torch), and whether the GPU has unified memory
(an integrated GPU sharing system RAM, e.g. NVIDIA Tegra/Jetson parts). It SHALL
resolve the CUDA wheel index by filtering candidate indexes to those whose CUDA
version is less than or equal to the host driver's CUDA version, then from the
driver-compatible `(index, torch version)` pairs where the torch version satisfies
the full torch specifier in `pyproject.toml` and the index's build list covers
every probed GPU, selecting the highest torch version and tie-breaking by the
newest CUDA index. Coverage for a GPU with compute capability `X.Y` means the
build list contains an exact `sm_XY` entry, a same-major SASS `sm_XZ` entry with
`Z ≤ Y`, or a PTX `compute_ZW` entry with `(Z, W) ≤ (X, Y)`. The documented
`DECISION_TABLE` SHALL label the selected result; it SHALL NOT drive selection. A
final CPU fallback entry SHALL always match so resolution cannot fail. The script
SHALL log the probe results and the resolved index (or operator override) before
installing torch.

On non-aarch64 hosts, unified-memory evidence SHALL be ignored for the CUDA
ladder with a warning; those hosts are treated as discrete. On aarch64 hosts
with driver CUDA ≥ 13.0 and unified or unknown memory, the resolver SHALL
select a cu13x index and require the GPU-vs-CPU numerical self-test; if the
self-test fails or cannot run, the installer SHALL reinstall CPU wheels and
record the fallback. On aarch64 hosts with unified memory and driver CUDA < 13.0,
the resolver SHALL select the CPU index with a note naming the Python 3.12
requirement and the manual `--index-url` override.

The script SHALL accept force flags `--cpu`, `--cuda`, `--rocm`, `--xpu`, and
`--mps` with their exact existing semantics, plus a new `--index-url <URL>`
override: when `--index-url` is given and the CUDA flavor is selected, the
script SHALL use that URL verbatim in place of the table-resolved index.
`--index-url` SHALL NOT change which flavor is detected or forced. A cuda
override result SHALL carry `torchaudio_unavailable`; with `--research` and no
`torchaudio` on that index, both installers SHALL refuse before installing torch.
Other flavors SHALL print `NOTICE: ignoring --index-url for flavor ...` and ignore
the override. The Bash and Python implementations SHALL agree on detection order,
resolution, and flag semantics.

#### Scenario: NVIDIA host installs CUDA wheels
- **WHEN** an operator runs `bash scripts/install.sh` on a dual-GPU x86_64
  workstation where `nvidia-smi` exists and returns success, the driver
  supports CUDA 12.9, and the GPUs are discrete with compute capabilities 8.9
  and 6.1
- **THEN** the resolver selects cu126 with the newest in-range torch (2.14.0),
  because cu126 is the newest index whose build list covers both GPUs at the
  highest in-range torch version, and invokes `pip install --index-url
  https://download.pytorch.org/whl/cu126 torch==2.14.0` (plus matching
  torchvision/torchaudio where available) in the venv

#### Scenario: CPU-only host installs CPU wheels
- **WHEN** an operator runs `bash scripts/install.sh` on a host where
  `nvidia-smi` is absent and no AMD/Intel/Apple accelerator is detected
- **THEN** the script invokes `pip install --index-url
  https://download.pytorch.org/whl/cpu` with the exact newest in-range torch in the venv

#### Scenario: AMD host installs ROCm wheels
- **WHEN** an operator runs `bash scripts/install.sh --rocm`, or on a host where
  `rocm-smi` is present (or `/opt/rocm` exists) and no NVIDIA driver is detected
- **THEN** the resolver probes the ROCm version and gfx targets and the script
  invokes `pip install` from the newest ROCm wheel index that carries an in-range
  torch and covers at least one requested target for that stack, warning about
  targets the chosen index does not cover, or refuses with a message naming the
  ROCm requirement when none fits

#### Scenario: Intel host installs XPU wheels
- **WHEN** an operator runs `bash scripts/install.sh --xpu`, or on a host where
  `xpu-smi`/`sycl-ls` is present and no NVIDIA or AMD accelerator is detected
- **THEN** the script installs the exact newest in-range torch and its recorded
  companions that the XPU wheel index (`https://download.pytorch.org/whl/xpu`)
  publishes for the host architecture, or refuses with a message naming the XPU
  flavor and the architecture when the index publishes none (for example on
  aarch64)

#### Scenario: Apple Silicon installs the default wheel for MPS
- **WHEN** an operator runs `bash scripts/install.sh --mps`, or on macOS `arm64`
  with no other accelerator forced
- **THEN** the script installs torch within the tested range from the default
  PyPI index with no `--index-url` and no exact pin, because the MPS backend ships
  in the standard macOS wheel and no MPS wheel data is recorded

#### Scenario: Idempotent re-run skips already-installed torch
- **WHEN** the script is run twice in succession with no change in
  hardware
- **THEN** the second run notes that torch is already installed at
  the right flavor (recognizing cuda, rocm, xpu, mps, or cpu) and skips the torch
  install step, but still runs `pip install -e .[test]` to pick up any pyproject
  changes

#### Scenario: Flavor change forces torch reinstallation
- **WHEN** the script is re-run and the effective target flavor differs from the
  installed torch build (for example a `+cpu` wheel is installed but CUDA wheels
  are wanted)
- **THEN** it force-reinstalls torch from the target source before writing the constraints file

#### Scenario: Re-run keeps installed torchaudio when not researching
- **WHEN** a host already has any `torchaudio` wheel installed, `--research` is
  not given, and the resolved CUDA index would otherwise omit `torchaudio` (for
  example `cu132`)
- **THEN** the resolver passes `--need-torchaudio` and keeps or installs the
  matching `torchaudio`, staying on an index that provides it (for example
  `cu130`) instead of switching to `cu132` and losing `torchaudio`; on the mps
  flavor, which has no resolved `torchaudio` pin, `torchaudio` is reinstalled from
  the default PyPI index under the torch constraints

#### Scenario: Coherent audio stack refuses an index without torchaudio
- **WHEN** an operator runs `bash scripts/install.sh --cuda --index-url
  https://download.pytorch.org/whl/cu132` on a host where `torchaudio` is already
  installed and `--research` is not given
- **THEN** both installers refuse before installing torch, because `torchaudio`
  is installed but the cu132 index publishes no `torchaudio` wheels for the
  resolved torch version, and they tell the operator to choose a different
  `--index-url` or uninstall `torchaudio` first

#### Scenario: aarch64 unified-memory host avoids the SBSA-only index
- **WHEN** an operator runs `bash scripts/install.sh` on an aarch64 host with a
  unified-memory Tegra/Jetson GPU whose compute capability is not covered by the
  in-range torch on an index, even under the same-major SASS rule and the
  recorded unified-host architecture list
- **THEN** the resolver does not select that index, so the installed
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

#### Scenario: aarch64 with unknown memory on JetPack 7
- **WHEN** an operator runs `bash scripts/install.sh` on an aarch64 host whose
  driver reports CUDA 13.x and unified-memory state is unknown
- **THEN** the resolver treats the host like a unified-memory Jetson, selects the
  newest cu13x index carrying an in-range torch, and requires the GPU-versus-CPU
  numerical self-test; if the self-test fails or cannot run, the installer
  reinstalls CPU wheels and records the fallback

#### Scenario: aarch64 unified-memory host on JetPack 6
- **WHEN** the driver on a unified-memory Jetson reports CUDA 12.x
- **THEN** the resolver selects the CPU index and the note names the Python 3.12
  requirement and the manual `--index-url` override

#### Scenario: PTX does not cover an older GPU
- **WHEN** the probed GPU has compute capability 7.5 and the candidate build
  list has no SASS entry with major version 7 or lower and its only PTX entry is
  `compute_120`
- **THEN** the build list does not cover that GPU, because PTX forward-compiles
  to newer GPUs but never backward; the resolver does not select an index whose
  only 7.x-or-older entry is a newer PTX version

#### Scenario: Newer driver resolves a newer CUDA index
- **WHEN** the probed driver reports support for CUDA 13.x and the GPUs'
  compute capabilities are covered by the in-range torch on a cu13x index
- **THEN** the script resolves that cu13x wheel index (e.g.
  `https://download.pytorch.org/whl/cu130`) and installs its newest in-range
  torch, rather than installing older CUDA builds against a newer driver

#### Scenario: Older driver falls back down the ordered table
- **WHEN** the probed driver's maximum supported CUDA version is older than the
  newest CUDA index (e.g. a driver that supports only CUDA 12.8, or only 11.8)
- **THEN** the script considers only indexes whose CUDA version the driver
  supports, never an index newer than the driver, selects among them the
  highest in-range torch covering every GPU, and selects CPU with a warning
  naming the torch range and the driver when no CUDA index is driver-compatible

#### Scenario: Operator override with --index-url
- **WHEN** an operator runs `bash scripts/install.sh --cuda --index-url
  https://download.pytorch.org/whl/cu126` on an NVIDIA host
- **THEN** the script invokes `pip install --index-url
  https://download.pytorch.org/whl/cu126` with the newest in-range torch in the venv,
  bypassing the table resolution, while flavor detection and the other force flags keep
  their existing semantics

#### Scenario: --research refuses an --index-url without torchaudio
- **WHEN** an operator runs `bash scripts/install.sh --cuda --research
  --index-url https://download.pytorch.org/whl/cu132` on an NVIDIA host
- **THEN** both installers refuse before installing torch, because `--research`
  requires torchaudio and the cu132 index publishes no torchaudio wheels

#### Scenario: Probe results and resolved index are logged
- **WHEN** the script selects the NVIDIA flavor, whether auto-detected or
  forced with `--cuda`
- **THEN** it logs the probed architecture, driver CUDA version, compute
  capability, unified-memory classification, and the wheel index it will use
  (resolved or operator override) before installing torch

#### Scenario: CPU re-run keeps a matching torchaudio
- **WHEN** the script is re-run with `--cpu` and the installed `torchaudio`
  matches the resolved CPU pin's base version and build tag
- **THEN** it keeps that `torchaudio` without uninstalling or downloading it again
