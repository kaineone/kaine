# Design: host-aware-accelerator-provisioning

## Context

`scripts/install.sh` hardcodes `NVIDIA_INDEX_URL="https://download.pytorch.org/whl/cu128"` and applies it whenever `nvidia-smi` succeeds, blind to CPU architecture, driver CUDA version, and compute capability. On aarch64 that index serves SBSA builds for sm_90/sm_100: they import cleanly, then fail at the first kernel launch with "no kernel image is available for execution on the device". A CUDA 13.x driver is served cu128 wheels. Separately, `kaine/hardware.py::describe_host()` has no unified-memory concept, so integrated-GPU hosts (NVIDIA Tegra/Jetson, AMD APUs, Apple Silicon) — where NVML answers "Not Supported" for memory — are described as having no usable memory, and the `gpu-preflight` gate, which only understands "free VRAM below `min_free_vram_gb`", can refuse boot on an adequate host whose memory figures are merely unknowable.

The fix is a generalization around probed host facts, not a fork for any board. Index resolution is implemented once, in a new `kaine/wheel_index.py`; `scripts/install.sh` becomes a thin wrapper over `python -m kaine.wheel_index` (JSON in/out), and the first-run wizard reuses the same module, so there is exactly one decision table and one fallback ladder.

## Goals

- Replace the hardcoded CUDA index with probe-driven selection (arch × driver CUDA × compute capability × unified-memory-ness) plus an operator override.
- Give `describe_host()` unified-memory classification with per-pool figures, provenance, and explicit unknown markers; JSON-serializable; never raises.
- Give `gpu-preflight` three memory states: known-discrete, known-unified, unknown.
- Give the first-run wizard PTX-aware mismatch detection and a consented corrective install.

## Non-Goals

- No change to the semantics of `--cpu --cuda --rocm --xpu --mps`.
- No Tegra/Jetson wheel builds from upstream indexes; Tegra hosts are directed to JetPack-provided indexes via `--index-url`.
- No change to ROCm/XPU/MPS/CPU detection order, index URLs, or existing gate messages.

## Decision 1: wheel-index decision table and fallback ladder

Probes (each fail-soft; a failed probe yields `unknown`, never an exception):

- **arch** — `platform.machine()`, normalized to `x86_64`, `aarch64`, or `other`.
- **driver CUDA** — the `CUDA Version` field of `nvidia-smi` output; fallback NVML `nvmlSystemGetCudaDriverVersion_v2()` (e.g. `12080` → `12.8`); else `unknown`.
- **compute capability** — per NVIDIA device via NVML `nvmlDeviceGetCudaComputeCapability`, fallback `torch.cuda.get_device_properties()` major/minor.
- **unified-memory classification** — per Decision 2.

Decision table (binding for the rows shown; the `cc guard` column references `INDEX_ARCH_MAP`, the authoritative arch→sm constant in `kaine/wheel_index.py`):

| # | CPU arch | Driver CUDA | Unified memory | cc guard | Index URL |
|---|---|---|---|---|---|
| 1 | x86_64 | ≥ 13.0 | no | cc covered by cu130 map (SASS or PTX) | `https://download.pytorch.org/whl/cu130` |
| 2 | x86_64 | 12.8 – 12.9 | no | cc covered by cu128 map | `https://download.pytorch.org/whl/cu128` |
| 3 | x86_64 | 12.5 – 12.7 | no | cc covered by cu126 map | `https://download.pytorch.org/whl/cu126` |
| 4 | x86_64 | 12.1 – 12.4 | no | cc covered by cu121 map | `https://download.pytorch.org/whl/cu121` |
| 5 | x86_64 | 11.8 – 12.0 | no | cc covered by cu118 map | `https://download.pytorch.org/whl/cu118` |
| 6 | x86_64 | < 11.8 or unknown | any | — | CPU index + warning |
| 7 | aarch64 | ≥ 13.0 | no | sm_90 / sm_100 or PTX (per map) | `https://download.pytorch.org/whl/cu130` |
| 8 | aarch64 | 12.8 – 12.9 | no | sm_90 / sm_100 or PTX (per map) | `https://download.pytorch.org/whl/cu128` |
| 9 | aarch64 | 12.5 – 12.7 | no | sm_90 or PTX (per map) | `https://download.pytorch.org/whl/cu126` |
| 10 | aarch64 | any | **yes** | — (Tegra sm_72/sm_87 served by no upstream index) | CPU index + warning (JetPack pointer) |
| 11 | aarch64 | < 12.5 or unknown | any | — | CPU index + warning |
| 12 | other | any | any | — | CPU index + warning |

Ladder (normative where it refines the table):

1. Build candidates: every `cuX.Y` index with `X.Y ≤` driver CUDA, **newest first**. A newer driver may run an older index (driver backward compatibility); the reverse is never attempted.
2. Architecture filter: drop candidates whose `INDEX_ARCH_MAP` entry lacks the host arch (x86_64 lines and aarch64 SBSA lines only; any other arch → empty candidate list).
3. Compute-capability filter: keep a candidate only if **every** probed NVIDIA device is covered — exact `sm_XY`, or a `sm_ZW+PTX` / `compute_ZW` entry with `(Z,W) ≥ (X,Y)`. PTX counts as coverage and the selection is annotated as JIT-from-PTX.
4. Unified-memory exclusion: if any probed NVIDIA device is **positively** classified unified, drop all candidates (upstream wheels carry no Tegra SASS). An `unknown` classification never excludes — a discrete host with broken NVML must still receive its wheel.
5. First survivor wins; if it is older than the newest candidate that passed filters 1–2, emit a downgrade note naming both index versions.
6. Exhaustion → CPU index (`https://download.pytorch.org/whl/cpu`, the same index `--cpu` uses today) **with a warning** stating the probed arch, driver CUDA, per-device cc, memory classification, the terminal rejection reason, and the `--index-url` remediation (for Tegra, the JetPack-provided index).

`kaine/wheel_index.py` emits `{variant, index_url, probes, selected_reason, rejected: [{index, reason}], warnings[]}`; `install.sh` exports the URL as `NVIDIA_INDEX_URL` and logs the JSON verbatim.

### Requirement: Host-aware CUDA wheel index selection
The installer SHALL select the CUDA wheel index from the probed CPU architecture, driver CUDA version, per-device compute capability, and unified-memory classification using the decision table in this section, and SHALL NOT hardcode any single CUDA index as an unconditional default; every probe failure SHALL degrade to `unknown` and route selection through the fallback ladder rather than raising or guessing.

#### Scenario: CUDA 13.x driver is no longer served cu128
- **WHEN** auto-detection runs on a host whose `nvidia-smi` reports CUDA Version 13.0 with an x86_64 CPU and a discrete cc 9.0 device
- **THEN** the selected index is `https://download.pytorch.org/whl/cu130` and the install log records the resolved URL together with the probe values that produced it

#### Scenario: aarch64 receives the SBSA line only when its compute capability is served
- **WHEN** auto-detection runs on aarch64 with a CUDA 12.8 driver and a discrete device of compute capability 9.0
- **THEN** the cu128 index is selected, whereas a device of compute capability 8.7 causes all SBSA candidates to be rejected and the ladder to terminate at the CPU index with a warning naming the unserved compute capability

#### Scenario: dual-GPU coverage is all-or-nothing
- **WHEN** two NVIDIA devices are probed and the newest candidate index covers only one of their compute capabilities
- **THEN** that candidate is rejected and the ladder continues to the newest index covering both devices before any CPU fallback

### Requirement: Ordered fallback ladder terminating at the CPU index
The installer SHALL evaluate CUDA index candidates in descending driver-CUDA order under the architecture, all-devices compute-capability (SASS or PTX), and unified-memory filters, and SHALL terminate at the CPU index with a warning when no candidate survives; the warning SHALL name the probed architecture, driver CUDA version, compute capability, memory classification, the reason the ladder exhausted, and the `--index-url` remediation.

#### Scenario: driver older than any packaged index
- **WHEN** the probed driver CUDA version is below the oldest index in the table (e.g. CUDA 11.4) or cannot be determined at all
- **THEN** the candidate list is empty, the CPU index is used, and the warning reports the too-old-or-unknown driver as the terminal reason without attempting any CUDA install

#### Scenario: PTX-only coverage is accepted but annotated
- **WHEN** the newest surviving index ships no exact SASS for the device's compute capability but contains a `+PTX` entry at or above it
- **THEN** that index is selected and the install log and wizard output annotate that first kernel launches will JIT-compile from PTX

#### Scenario: downgrade to an older line to satisfy compute capability
- **WHEN** the newest candidate's architecture map lacks the device's compute capability while an older candidate covers it
- **THEN** the older candidate is selected and a downgrade note naming both index versions is emitted

## Decision 2: unified-memory detection strategy

`describe_host()` classifies each accelerator's memory via an ordered evidence ladder; the first positive evidence sets the classification, and every applied figure records its provenance:

1. **NVML memory probe** — `nvmlDeviceGetMemoryInfo`: `total > 0` → `discrete` with figures `source: "nvml"`; `NVML_ERROR_NOT_SUPPORTED` or `total == 0` → figures are `null` with `reason: "nvml: not supported"` and the device becomes a *unified candidate* (a hint only — never sufficient on its own).
2. **CUDA integrated-device attribute** — `cuDeviceGetAttribute(&v, CU_DEVICE_ATTRIBUTE_INTEGRATED /* 18 */, dev)` via ctypes (equivalent: `cudaDeviceProp.integrated`): `1` → `unified` (positive); `0` → `discrete` (positive) even when NVML figures are unavailable.
3. **Platform class** — Darwin + arm64 → `unified` (Apple Silicon); Linux + aarch64 with Tegra markers (`/proc/device-tree/model` or `compatible` containing `nvidia,tegra`, or `/etc/nv_tegra_release` present) → `unified`.
4. **APU carve-out signature** — amdgpu sysfs `mem_info_vram_total` at or below the carve-out ceiling (4 GiB) while `mem_info_gtt_total` ≥ 50% of installed system RAM → `unified`, with two pools (BIOS carve-out and GTT), `source: "sysfs-amdgpu"`.
5. Otherwise → `unknown`.

NVML failure alone never yields `unified` (a discrete GPU with broken NVML must not be subjected to system-memory thresholds); it yields `unknown` figures. Output shape per accelerator:

"memory": {
  "classification": "discrete|unified|unknown",
  "evidence": "nvml-figures|cuda-integrated-attr|platform-tegra|platform-apple|apu-carveout|none",
  "pools": [
    {"name": "vram", "total_bytes": 24564, "free_bytes": 23800, "source": "nvml"},
    {"name": "system", "total_bytes": 32768, "available_bytes": 30000, "source": "proc-meminfo"}
  ],
  "unknown_reason": null
}

### Requirement: Unified-memory classification with provenance in describe_host
`describe_host()` SHALL classify each accelerator's memory as `discrete`, `unified`, or `unknown` using the ordered evidence ladder (NVML figures, CUDA integrated-device attribute, platform class, APU carve-out signature), SHALL report per-pool figures each carrying a `source` provenance tag, SHALL represent unknowable figures as explicit `null` values accompanied by a machine-readable `unknown_reason` (never zeros, never absent keys), and SHALL remain JSON-serializable and never raise regardless of probe failures.

#### Scenario: Tegra is classified unified from corroborated evidence
- **WHEN** NVML returns "Not Supported" for device memory and `CU_DEVICE_ATTRIBUTE_INTEGRATED` reads 1 on a Tegra platform
- **THEN** the device is classified `unified`, the reported pool is system memory with its provenance tag, and no VRAM pool is fabricated

#### Scenario: NVML failure alone never yields unified
- **WHEN** NVML memory reporting fails or returns zero on a device whose integrated attribute reads 0 and which matches no platform or APU signature
- **THEN** the device is classified `discrete` with `null` figures and an explicit `unknown_reason`, so preflight treats the figures — not the class — as unknowable

#### Scenario: total probe failure degrades to unknown without raising
- **WHEN** every memory probe is unavailable (no NVML, no CUDA runtime, unrecognized platform)
- **THEN** `describe_host()` returns `classification: "unknown"` with `null` figures and a populated `unknown_reason`, returns normally, and its output serializes to JSON

#### Scenario: AMD APU carve-out signature
- **WHEN** amdgpu sysfs reports `mem_info_vram_total` at or below 4 GiB while `mem_info_gtt_total` is at least half of installed system RAM
- **THEN** the device is classified `unified` with carve-out and GTT pools each carrying `source: "sysfs-amdgpu"`

## Decision 3: gpu-preflight three memory states

The gate consumes `classification` plus pools. `known-discrete` preserves today's behaviour exactly (refuse when free VRAM < `min_free_vram_gb`). `known-unified` applies the same configured threshold to **available** system memory (`MemAvailable`, i.e. reclaimable — not bare free). `unknown` passes and annotates; unknowable memory never refuses boot on its own, though all other independent gates still apply.

### Requirement: gpu-preflight three-state memory handling
The `gpu-preflight` gate SHALL evaluate exactly one of three memory states — `known-discrete` (unchanged: refuse boot when free VRAM is below `min_free_vram_gb`), `known-unified` (apply `min_free_vram_gb` to available system memory), and `unknown` (pass, annotating its structured output with `memory_state: "unknown"`, the reason, and `threshold_unenforced: true`) — and SHALL NOT refuse boot on unknowable memory alone.

#### Scenario: known-discrete refusal is unchanged
- **WHEN** the device is classified discrete with NVML free VRAM below `min_free_vram_gb`
- **THEN** the gate refuses boot with the same message and exit behaviour as before this change

#### Scenario: known-unified threshold applied to system memory
- **WHEN** the device is classified unified and available system memory is below `min_free_vram_gb`
- **THEN** the gate refuses boot with a unified-aware message naming the measured available bytes, and passes when available system memory meets the threshold

#### Scenario: unknowable memory passes with annotation
- **WHEN** memory classification is `unknown` and no other gate fails
- **THEN** the gate passes boot and its JSON output records `memory_state: "unknown"`, the reason, and that `min_free_vram_gb` was not enforced

## Decision 4: override and precedence semantics

Precedence, highest first:

1. `--index-url <url>` — operator override of the resolved URL; beats all probes; used verbatim; never silently falls back.
2. Force flags `--cpu --cuda --rocm --xpu --mps` — beat auto-detection for **variant** selection; exact existing semantics; mutually exclusive as today.
3. Host-aware decision table — resolves the URL for the selected variant when no `--index-url` is given (`--cpu`/`--rocm`/`--xpu`/`--mps` keep their existing fixed indexes; only the CUDA variant is table-resolved).
4. CPU index + warning — terminal fallback of the ladder.

Combination rules: `--index-url` + force flag → flag picks the variant, override picks the URL. `--index-url` alone → variant auto-detected, URL forced. A forced CUDA variant for which the table yields no candidate (unified Tegra) aborts with guidance rather than installing a known-incompatible wheel.

### Requirement: --index-url operator override
`scripts/install.sh` SHALL accept `--index-url <url>` and, when provided, SHALL use that URL verbatim for the selected variant without running index-selection probes, SHALL NOT silently fall back to a probed index on install failure, SHALL abort before any package operation on an empty or malformed value, and SHALL print a loud mismatch warning when the override's variant tag (e.g. `cu126`, `cpu`, `rocm6`) disagrees with the selected accelerator variant.

#### Scenario: override beats probes
- **WHEN** `--index-url https://download.pytorch.org/whl/cu126` is passed on a host that auto-detection would serve cu130
- **THEN** pip is invoked with the operator's URL exactly and the log records the URL provenance as operator-override rather than probe-derived

#### Scenario: malformed override fails fast
- **WHEN** `--index-url` is passed with an empty or non-URL value
- **THEN** the installer exits with a usage error before any package operation and does not fall back to probe-derived selection

#### Scenario: variant mismatch is warned, not blocked
- **WHEN** `--index-url` points at a CUDA index while a force flag or auto-detection selected the CPU variant
- **THEN** the installer prints a mismatch warning naming both variants and proceeds with the operator's URL

### Requirement: Force-flag precedence over auto-detection
The force flags `--cpu`, `--cuda`, `--rocm`, `--xpu`, and `--mps` SHALL retain their exact existing semantics — selecting the accelerator variant and suppressing accelerator auto-detection — and SHALL take precedence over probe-derived variant selection; when `--cuda` is given without `--index-url`, the wheel index SHALL still be resolved host-aware by the decision table; and when the table yields no candidate for a forced CUDA variant, the installer SHALL abort with an actionable error directing the operator to `--index-url` rather than silently installing a known-incompatible wheel.

#### Scenario: --cpu bypasses accelerator probes for variant selection
- **WHEN** `--cpu` is passed on a host with a fully working NVIDIA stack
- **THEN** the CPU index is used, no CUDA wheel is installed, and no probe influences the variant (probes may still populate `describe_host`)

#### Scenario: --cuda on a servable host keeps the table-driven URL
- **WHEN** `--cuda` is passed without `--index-url` on an x86_64 host with a CUDA 12.9 driver
- **THEN** the CUDA variant is forced and the index is cu128 exactly as the table dictates

#### Scenario: --cuda on an unservable unified host aborts with guidance
- **WHEN** `--cuda` is passed without `--index-url` on a Tegra host whose compute capability no upstream index serves
- **THEN** the installer aborts before installing anything, with an error naming the probed compute capability and instructing the operator to supply `--index-url` (e.g. a JetPack-provided index)

## Decision 5: wizard mismatch detection and consented corrective install

The first-run wizard compares the installed runtime against the probed host: driver CUDA capability vs `torch.version.cuda` (mismatch when torch requires a newer driver than the host provides, i.e. torch major > driver major, or equal majors with torch minor > driver minor — torch older than the driver is fine), and each device's compute capability vs `torch.cuda.get_arch_list()` PTX-aware (satisfied iff the list contains exact `sm_XY`, or any `sm_ZW+PTX` / `compute_ZW` entry with `(Z,W) ≥ (X,Y)`). On mismatch it presents both sides of the finding, proposes the corrective reinstall (re-running `scripts/install.sh` with the table-resolved URL passed explicitly as `--index-url`, so the corrective path is auditable), and proceeds only on explicit affirmative consent with decline as the default; a decline persists an annotation and does not re-prompt in the same boot; a failed corrective install surfaces the installer output unmasked.

### Requirement: Wizard mismatch detection and consented corrective install
The first-run wizard SHALL detect accelerator/runtime mismatch by comparing the probed driver CUDA version against `torch.version.cuda` and each device's compute capability against `torch.cuda.get_arch_list()` using the PTX-aware rule, SHALL on mismatch propose the corrective reinstall using the resolved index and proceed only on explicit affirmative consent (default: decline), SHALL on decline continue with a persistent annotation of the mismatch and the decline, and SHALL on a failed corrective install surface the installer output without masking the failure.

#### Scenario: runtime newer than driver is flagged
- **WHEN** the wizard runs where `torch.version.cuda` is 12.8 but the driver's CUDA capability is 12.4
- **THEN** the wizard reports the driver/runtime mismatch with both versions and offers the consented corrective install targeting the table-resolved index for the host

#### Scenario: unserved compute capability is flagged PTX-aware
- **WHEN** the device compute capability is 12.0 and `torch.cuda.get_arch_list()` contains only `sm_90` and `sm_90+PTX`
- **THEN** the wizard flags the architecture gap (no SASS and no PTX entry at or above cc 12.0) and offers the consented corrective install

#### Scenario: declined corrective install continues with annotation
- **WHEN** the operator declines the offered corrective install
- **THEN** the wizard continues startup, records the mismatch and the decline in the persistent host annotation, and does not re-prompt within the same boot

## Decision 6: non-regression guard

The dual-GPU x86_64 NVIDIA workstation default, ROCm, XPU, MPS, and CPU-only paths are pinned by requirement: same variant, same index URLs, same detection order, same gate messages, and no new interactive prompts on hosts where the installed accelerator already matches the probed host.

### Requirement: Non-regression of existing accelerator paths
The change SHALL NOT alter outcomes for the dual-GPU x86_64 NVIDIA workstation default, ROCm, XPU, MPS, or CPU-only hosts: a dual-GPU x86_64 host with a CUDA 12.8 driver SHALL resolve to the same cu128 URL in use today, ROCm/XPU/MPS/CPU-only selection SHALL keep their existing detection order, index URLs, and flags, and no new interactive prompt SHALL appear on hosts whose installed accelerator matches the probed host.

#### Scenario: dual-GPU workstation default is byte-identical
- **WHEN** auto-detection runs on x86_64 with a CUDA 12.8 driver and two discrete cc 8.9 devices
- **THEN** the resolved index is `https://download.pytorch.org/whl/cu128`, identical to the pre-change hardcoded value, with both devices recorded as covered

#### Scenario: non-CUDA paths are untouched
- **WHEN** the installer runs on a ROCm-only, XPU, Apple Silicon (MPS), or CPU-only host
- **THEN** the selected variant and index are exactly those chosen before this change, and the new probes neither raise nor alter the outcome

#### Scenario: no redundant wizard prompt on healthy hosts
- **WHEN** the first-run wizard runs where `torch.version.cuda` is compatible with the driver and every device cc is satisfied per the PTX-aware check
- **THEN** no mismatch prompt is shown and first-run proceeds as before

## Risks / Trade-offs

- `INDEX_ARCH_MAP` can drift from upstream wheel contents; it is a versioned data constant, unknown index names never match (safe fall-through), and updates ride the normal release process.
- The conservative `index ≤ driver CUDA` rule may pick older wheels than CUDA minor-version compatibility would allow; correctness at first kernel launch is preferred over newest-feature access, and `--index-url` exists for operators who disagree.
- PTX-only selections incur JIT latency on first launch; this is annotated, not blocked.
- Tegra operators must supply a JetPack-provided index via `--index-url`; the ladder warning and the `--cuda` abort error both say so explicitly.