## Why

Accelerator provisioning in KAINE currently assumes one host shape: x86_64, discrete NVIDIA GPUs, a driver that tolerates cu128 wheels. Three defects follow from that single assumption.

1. **Hardcoded wheel index.** `scripts/install.sh` sets
   `NVIDIA_INDEX_URL="https://download.pytorch.org/whl/cu128"` and uses it whenever
   `nvidia-smi` succeeds. The script never reads CPU architecture, the driver's reported
   CUDA version, or the GPU's compute capability. Two failure modes result: on aarch64
   that index serves SBSA builds targeting sm_90/sm_100, so torch imports cleanly and
   then the first kernel launch dies with "no kernel image is available for execution on
   the device" — a failure that surfaces far from the install step, where it could be
   fixed cheaply. And a host with a CUDA 13.x driver still receives cu128 wheels, pinning
   the runtime below what the driver supports.

2. **No unified-memory concept.** `kaine/hardware.py::describe_host()` only models a
   discrete VRAM pool. On integrated GPUs that share system RAM — NVIDIA Tegra/Jetson,
   AMD APUs, Apple Silicon — there is no separate VRAM pool and NVML answers "Not
   Supported" for memory queries. `describe_host()` therefore reports missing or zero
   VRAM on hosts that have ample usable memory, and that wrong figure feeds the
   preflight gate.

3. **"Unknown" conflated with "short".** The `gpu-preflight` gate refuses boot when free
   VRAM is below `min_free_vram_gb` but defines no behavior for the case where free VRAM
   cannot be measured at all. An adequate host can be refused boot because "unknowable"
   is treated as — or is simply undefined next to — "insufficient". The gate cannot
   distinguish a host that is short of memory from a host whose memory it cannot see.

This is one defect in three places: the pipeline assumes a discrete-NVIDIA x86_64 host
end to end. The fix generalizes each stage to consume probed host facts instead of
assumptions. It is a **generalization, not a host-specific fork**: no board name, DMI
string, or model-specific branch appears anywhere in the change — the same probe
signals `install.sh` already shells out to (`nvidia-smi`, `uname`) become inputs to a
documented fallback table, which is data rather than per-host code. **Consent is
preserved and extended**: nothing is ever installed without an explicit operator yes,
and boot is never refused on memory the host cannot report.

## What Changes

- `scripts/install.sh` replaces the hardcoded `NVIDIA_INDEX_URL` with resolution from
  probed facts — CPU architecture, driver CUDA version, GPU compute capability, and
  unified-memory-ness — via a documented, ordered fallback table. A new `--index-url`
  operator override wins over the table. The force flags `--cpu --cuda --rocm --xpu
  --mps` keep their exact current semantics.
- `kaine/hardware.py::describe_host()` classifies accelerator memory as discrete,
  unified, or unknown, and reports per-pool figures with provenance (which probe
  produced each number) and explicit unknown markers. Output stays JSON-serializable;
  the function still never raises.
- The `gpu-preflight` gate learns three memory states: known-discrete (threshold on
  free VRAM, unchanged), known-unified (threshold applied to available system memory),
  and unknown (passes with an annotation; never refuses boot on unknowable memory
  alone).
- The first-run wizard detects accelerator/runtime mismatch — driver CUDA version vs
  `torch.version.cuda`, and GPU compute capability vs `torch.cuda.get_arch_list()`,
  PTX-aware — and offers a corrective install that runs only on explicit consent.
- Non-goals: ROCm, XPU, MPS, and CPU-only provisioning keep their current behavior; the
  dual-GPU x86_64 NVIDIA workstation default must behave identically whenever its
  probed facts match today's hardcoded assumptions.

### Requirement: Probed CUDA wheel index resolution
`scripts/install.sh` SHALL resolve the NVIDIA wheel index from probed host facts — CPU architecture, driver CUDA version, GPU compute capability, and unified-memory classification — by selecting the first matching row of a documented, ordered fallback table, SHALL log the probe values together with the resolved index, and SHALL NOT carry an unconditionally-used hardcoded index URL.

#### Scenario: Default workstation path is unchanged
- **WHEN** installation runs on the existing dual-GPU x86_64 NVIDIA workstation whose probed facts match today's hardcoded assumption (x86_64, discrete GPUs, driver CUDA version served by cu128)
- **THEN** the resolved index is exactly `https://download.pytorch.org/whl/cu128` and the installed wheel set is identical to current behavior

#### Scenario: aarch64 mismatch is avoided at install time
- **WHEN** installation runs on aarch64 whose probed compute capability is not served by the SBSA cu128 wheels
- **THEN** the fallback table resolves an index whose wheels contain kernels for the probed compute capability, and the install log records architecture, driver CUDA version, compute capability, and unified-memory classification alongside the chosen index

#### Scenario: Driver newer than the hardcoded index
- **WHEN** the probed driver reports CUDA 13.x
- **THEN** the table resolves a cu13x index rather than serving cu128 wheels, or — if no table row matches — the installer aborts with a diagnostic listing the probe values instead of installing a wheel that cannot run

#### Scenario: Operator override wins
- **WHEN** the operator passes `--index-url <url>`
- **THEN** that URL is used verbatim, takes precedence over the fallback table, and the override is recorded in the install log

#### Scenario: Force flags keep exact semantics
- **WHEN** any of `--cpu`, `--cuda`, `--rocm`, `--xpu`, or `--mps` is passed
- **THEN** each flag forces exactly the accelerator and package set it forces today; the fallback table only changes where the CUDA index URL comes from and alters no flag's meaning

#### Scenario: No accelerator means CPU-only as before
- **WHEN** no supported accelerator is probed
- **THEN** the installer takes the existing CPU-only path unchanged and never consults the NVIDIA fallback table

### Requirement: Unified-memory classification in describe_host()
`kaine/hardware.py::describe_host()` SHALL classify accelerator memory as `discrete`, `unified`, or `unknown`, SHALL report per-pool figures each with provenance naming the probe that produced it (e.g., NVML, psutil, `/proc/meminfo`), SHALL use explicit unknown markers — never zero or silently absent fields — for figures it cannot determine, SHALL remain JSON-serializable, and SHALL never raise.

#### Scenario: Discrete host unchanged
- **WHEN** `describe_host()` runs on a host with discrete GPUs (e.g., the dual-GPU x86_64 NVIDIA workstation) and NVML answers memory queries
- **THEN** memory is classified `discrete`, per-GPU VRAM figures carry NVML provenance, and every field existing consumers read is present with the same meaning as before

#### Scenario: Unified-memory host reports usable memory
- **WHEN** `describe_host()` runs on an integrated-GPU host sharing system RAM (NVIDIA Tegra/Jetson, AMD APU, Apple Silicon) and NVML returns "Not Supported" for memory
- **THEN** memory is classified `unified` and the report carries system-memory figures with provenance instead of missing or zero VRAM

#### Scenario: Unknowable figures are explicit
- **WHEN** a memory figure cannot be determined on any host
- **THEN** the corresponding field is an explicit unknown marker with a reason, the affected pool is classified `unknown`, and the returned object is still a complete JSON-serializable dict

#### Scenario: Probe failures never propagate
- **WHEN** NVML or any underlying probe raises while `describe_host()` is running
- **THEN** the exception is contained, the affected figures degrade to unknown markers, and `describe_host()` returns normally

### Requirement: Three-state gpu-preflight memory gate
The `gpu-preflight` gate SHALL evaluate memory in exactly three states: known-discrete — apply `min_free_vram_gb` to free VRAM exactly as today; known-unified — apply `min_free_vram_gb` to available system memory; unknown — pass with an annotation and SHALL NOT refuse boot on unknowable memory alone.

#### Scenario: Known-discrete shortfall still refuses boot
- **WHEN** memory is known-discrete and free VRAM is below `min_free_vram_gb`
- **THEN** the gate refuses boot with the same decision and message shape as today

#### Scenario: Known-unified shortfall refuses boot against system memory
- **WHEN** memory is known-unified and available system memory is below `min_free_vram_gb`
- **THEN** the gate refuses boot, stating that the unified pool (system memory) is short

#### Scenario: Known-unified adequate host boots
- **WHEN** memory is known-unified and available system memory meets `min_free_vram_gb`
- **THEN** the gate passes, where today the same host could be refused or fall into undefined behavior due to missing or zero VRAM

#### Scenario: Unknown memory passes with annotation
- **WHEN** the memory state is unknown because figures are unknowable
- **THEN** the gate passes, annotates the decision record with the unknown-memory state and its reason, and boot is not refused on that basis

#### Scenario: Unknown memory does not mask other failures
- **WHEN** memory state is unknown and an independent preflight check fails
- **THEN** boot is still refused by that failing check; the unknown-memory pass grants no blanket approval

### Requirement: Wizard mismatch detection with consented correction
The first-run wizard SHALL detect accelerator/runtime mismatch by comparing the probed driver CUDA version against `torch.version.cuda` and the GPU compute capability against `torch.cuda.get_arch_list()` with PTX-awareness (a compatible PTX entry satisfies an unmatched SASS capability), SHALL present the mismatch and the proposed corrective install (re-running the installer with the resolved index), and SHALL execute any corrective install only after explicit operator consent.

#### Scenario: Runtime/driver mismatch offered, then consented
- **WHEN** the wizard detects that `torch.version.cuda` is incompatible with the probed driver CUDA version
- **THEN** the wizard displays both values and the proposed corrective install, and performs the install only after the operator explicitly consents

#### Scenario: Compute-capability mismatch is PTX-aware
- **WHEN** the GPU's compute capability has no SASS entry in `torch.cuda.get_arch_list()` but a compatible PTX entry exists
- **THEN** the wizard treats the runtime as compatible and does not prompt

#### Scenario: Declined correction changes nothing
- **WHEN** the operator declines the offered corrective install
- **THEN** nothing is installed or modified, the wizard continues, and the declined mismatch is recorded for later runs

#### Scenario: No mismatch, no new prompts
- **WHEN** the driver CUDA version and compute capability are compatible with the installed torch
- **THEN** the wizard's flow and prompts are exactly as before this change