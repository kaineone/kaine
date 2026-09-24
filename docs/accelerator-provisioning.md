<!-- SPDX-License-Identifier: LicenseRef-CAL-0.2 -->
<!-- Copyright (c) 2026 Kaine.One <kaine.one@tuta.com> -->

# Accelerator Provisioning

KAINE auto-detects accelerator hardware at install time and at boot time. The installer resolves the correct PyTorch wheel index from probed host properties, and the pre-boot memory gate verifies that the accelerator has headroom before any module initializes. This page documents both mechanisms for operators.

## CUDA wheel index resolution

`scripts/install.sh` resolves the CUDA wheel index at install time by invoking `python -m kaine.wheel_index`. The resolver probes four host properties:

- CPU architecture (`uname`)
- driver CUDA version — first from the `nvidia-smi` header, then from NVML
- compute capability of every probed GPU — first from NVML, then `nvidia-smi --query-gpu=compute_cap`, then torch
- unified-memory state (`kaine.hostmem`)

### Decision table

The table below is `kaine.wheel_index.DECISION_TABLE` rendered for operators. It is not a first-match lookup. The resolver labels the selected result with the matching row number; the actual selection is driven by the algorithm described in the following paragraphs.

| Row | Arch    | Driver CUDA       | Unified | CC guard | Index          | Warning |
|-----|---------|-------------------|---------|----------|----------------|---------|
| 1   | x86_64  | ≥ 13.2            | no      | cu132    | cu132          | no      |
| 2   | x86_64  | 13.0–13.1         | no      | cu130    | cu130          | no      |
| 3   | x86_64  | 12.9–12.9         | no      | cu129    | cu129          | no      |
| 4   | x86_64  | 12.8–12.8         | no      | cu128    | cu128          | no      |
| 5   | x86_64  | 12.6–12.7         | no      | cu126    | cu126          | no      |
| 6   | x86_64  | ≤ 12.5 or unknown | any     | —        | CPU            | yes     |
| 7   | aarch64 | ≥ 13.2            | no      | cu132    | cu132          | no      |
| 8   | aarch64 | 13.0–13.1         | no      | cu130    | cu130          | no      |
| 9   | aarch64 | 12.9–12.9         | no      | cu129    | cu129          | no      |
| 10  | aarch64 | 12.8–12.8         | no      | cu128    | cu128          | no      |
| 11  | aarch64 | 12.6–12.7         | no      | cu126    | cu126          | no      |
| 12  | aarch64 | ≤ 12.5 or unknown | any     | —        | CPU            | yes     |
| 13  | aarch64 | ≥ 13.2            | yes     | cu132    | cu132          | no      |
| 14  | aarch64 | 13.0–13.1         | yes     | cu130    | cu130          | no      |
| 15  | aarch64 | any or unknown    | yes     | —        | CPU            | yes     |
| 16  | other   | any or unknown    | any     | —        | CPU            | yes     |

An aarch64 host whose memory classification is unknown matches the non-unified rows; with driver CUDA ≥ 13.0 the resolver still requires the GPU-vs-CPU numerical self-test for it.

Rows with a CC guard require every probed GPU's compute capability to be covered by the selected index's build list. Coverage for a GPU with compute capability `X.Y` means the build list contains one of:

- an exact `sm_XY` entry;
- a same-major SASS `sm_XZ` entry with `Z ≤ Y` (the highest such entry is used);
- a PTX `compute_ZW` entry with `(Z, W) ≤ (X, Y)`.

PTX forward-compiles to newer GPUs at load time; a PTX version newer than the GPU is not usable, so PTX never covers an older GPU.

The resolver algorithm is:

1. Filter candidate indexes to those whose CUDA version is less than or equal to the host driver's CUDA version.
2. From the driver-compatible `(index, torch version)` pairs where the torch version satisfies the tested range in `pyproject.toml` and the index's build list covers every probed GPU, select the highest torch version.
3. Tie-break by the newest CUDA index.

For example, an x86_64 host with driver CUDA 12.9 and two GPUs with compute capabilities 8.9 and 6.1 resolves to cu126 with torch 2.14.0, because cu126 is the newest index whose in-range torch covers both GPUs at the highest in-range torch version, not cu129 even though the driver supports it.

The tested `torch` range is declared in `pyproject.toml` (currently `>=2.9.1,<2.15`). It is a *bounded tested range*: the offline suite runs in CI at both ends of the range on the CPU index (the newest in-range torch, and the range's lower bound), accelerator hosts are verified manually and recorded in the Tested hosts table, Dependabot does not raise this bound automatically, and widening the range needs the CI job at both new ends plus a recorded smoke test on each accelerator family the change affects. Not every intermediate point is exercised.

When a CUDA index is selected, the resolver records the exact `torch`, `torchvision`, and `torchaudio` versions that match the selected index and installs those exact versions. The installer writes those exact versions into a constraints file so that later `pip install` calls cannot silently float to a different torch build.

Data provenance for the ladder lives in `kaine/wheel_data.py`, which records the published versions and architecture lists for each index (dated). Drift against the live indexes is reported by `python -m kaine.wheel_index --verify-indexes`.

The research install path (`scripts/install.sh --research`) always passes `--need-torchaudio` to the resolver. Because the cu132 index publishes no `torchaudio` wheels, hosts that would otherwise resolve to cu132 instead resolve to cu130 so that `torchaudio` is available. Audio-stack coherence triggers when any `torchaudio` wheel is installed and `--research` is not given: both installers still pass `--need-torchaudio` to the resolver, replace a `torchaudio` whose base version or local tag does not match the resolved stack, and keep a matching `torchaudio` on re-runs. The cpu and xpu flavors resolve the exact newest in-range `torch` recorded for the host architecture with its recorded `torchvision` and `torchaudio` companions; xpu wheels are recorded for x86_64 only and the installer refuses that flavor on other architectures. The mps flavor installs `torch` within the tested range from the default PyPI index without an exact `torchaudio` pin because no MPS wheel data is recorded, so `torchaudio` is reinstalled from PyPI under the torch constraints on each mps run. `torchaudio`'s last release is 2.11.0; torch 2.12–2.14 are paired with it by release timing only, and the resolver emits a warning saying no wheel metadata asserts that pairing.

If `torchaudio` is installed and the chosen index publishes no `torchaudio` for the resolved torch version, both installers refuse before installing `torch`, telling the operator to choose a different `--index-url` or uninstall `torchaudio` first to drop the audio stack.

### ROCm wheel index resolution

AMD hosts are resolved from the host ROCm version (read from `/opt/rocm/.info/version`, or overridden with `KAINE_ROCM_VERSION`) and the GFX targets (from `KAINE_ROCM_GFX`, else `rocminfo` agent names parsed even when `rocminfo` exits non-zero, else `rocm_agent_enumerator`; feature suffixes after `:` are stripped, `gfx000` and `-generic` are dropped, and `rocminfo` output that yields no usable target falls through to `rocm_agent_enumerator`). The installer prints `==> ROCm version: <v>; gfx targets: <list> (source: ...)`.

The resolver selects, among ROCm wheel indexes whose version is less than or equal to the host ROCm version, that publish an in-range `torch` for the host architecture, and whose build list covers at least one requested GFX target, the highest in-range torch then the newest ROCm index. It warns about targets the chosen index does not cover (suggesting `HIP_VISIBLE_DEVICES`) and refuses when none fits; there is no CUDA fallback.

### Jetson handling

Jetson hosts appear as aarch64 with unified memory.

- JetPack 7 (driver CUDA ≥ 13.0) resolves to a cu13x wheel index and runs a GPU-vs-CPU numerical self-test (`python -m kaine.accel_selftest`). If the self-test fails or cannot run, the installer reinstalls CPU wheels and writes `<venv>/kaine-accel-fallback.json` (index, torch, reason, date).
- JetPack 6 (driver CUDA < 13.0) resolves to CPU wheels with a note that a JetPack-provided CUDA wheel index is required. Python 3.12 is required for the upstream CPU wheels.

### Unified-memory note for non-aarch64 hosts

Unified-memory evidence is ignored for CUDA on non-aarch64 hosts: NVIDIA unified-memory GPUs are aarch64-only. If a non-aarch64 host reports unified memory, the resolver treats it as discrete for the CUDA ladder (the evidence likely comes from a non-NVIDIA integrated GPU) and surfaces a warning.

### Installer re-runs

The installer writes exact pins to `<venv>/kaine-torch-constraints.txt`. On re-run, it classifies the installed torch by its build metadata (`torch.version.hip` → rocm, `torch.version.cuda` → cuda, an XPU build → xpu, an MPS build on macOS arm64 → mps, else cpu) and compares it with the effective target flavor (cpu when the chosen index is the CPU index, for example after a self-test fallback). A flavor mismatch forces a reinstall; a matching flavor with a different pinned base version reinstalls; on `download.pytorch.org/whl/<tag>` indexes a local-tag mismatch forces a reinstall (untagged counts as cpu). A stale `torchaudio` (wrong base version or tag, or no pin and not needed) is uninstalled before the constraints file is written; when no pin applies but torchaudio is needed, a matching build tag is kept. When the self-test fails or cannot run, the installer reinstalls CPU wheels and writes `<venv>/kaine-accel-fallback.json` (index, torch, reason, date); later runs keep CPU wheels for that index/torch pair until `--retry-gpu`.

### Tested hosts

| Host | Accelerator | Index resolved / installed | torch | Verified |
|------|-------------|---------------------------|-------|----------|
| Development workstation (x86_64) | RTX 4070 SUPER + RTX 3070, driver CUDA 13.2 | cu132 from live probes; torch 2.14.0+cu130 installed | 2.14.0 | The full offline suite passes with CUDA available; no install from the cu132 index has been exercised on it. |
| CPU-only (x86_64) | none | cpu | 2.9.1 and 2.14.0 | The offline suite passes in CI. |

Other rows are added when a host is verified. No Jetson, ROCm, XPU, or Apple host has been verified yet.

### Operator override: `--index-url`

`--index-url <URL>` overrides the resolved CUDA wheel index for the cuda flavor only; other flavors print `NOTICE: ignoring --index-url for flavor ...`. A cuda override result carries `torchaudio_unavailable`. With `--research` and no `torchaudio` on that index, both installers refuse before installing torch.

Precedence, highest first:

1. Operator override (`--index-url`)
2. CUDA resolution algorithm
3. Terminal CPU fallback

Only the cuda flavor consults the CUDA resolution algorithm. The `--cpu` and `--xpu` flavors are resolved from the host architecture via `kaine.wheel_index` (a cpu host on an architecture the wheel data does not record, such as s390x, installs unpinned from the CPU index with a warning, as does a cpu host when the resolver cannot run; xpu refuses instead); `--mps` uses the default PyPI index with no exact pin; `--rocm` is resolved from the host ROCm version and GFX targets (see above).

## Pre-boot GPU headroom check

The `[gpu_preflight]` section in `config/kaine.toml` controls a cooperative pre-boot memory check. It ships disabled; enable it with:

```toml
[gpu_preflight]
enabled = true
```

Before boot, the gate classifies memory into one of three states:

- **known-discrete** — a dedicated VRAM pool (e.g. desktop NVIDIA). The threshold is applied per device.
- **known-unified** — system-shared memory (Jetson, AMD APU, Apple Silicon). The threshold is applied to available system memory.
- **unknown** — free capacity could not be determined. The gate always passes with an annotation; unknowable memory alone never refuses boot.

The threshold key is `min_free_vram_gb` (default `2.0`):

```toml
[gpu_preflight]
enabled = true
min_free_vram_gb = 2.0
```

To override the gate, set the environment variable `KAINE_GPU_PREFLIGHT_APPROVED=1`.

The gate is report-only: it never terminates processes. When it runs, it queries `/v1/models` on the model server to report what is currently resident.

## Unified-memory classification

`kaine.hostmem` classifies host memory with a detection ladder; the first positive verdict wins:

1. **NVML figures** (via ctypes) — discrete if real figures are available; otherwise fall through.
2. **CUDA integrated-device attribute** (via ctypes/torch) — attribute 18: `1` = unified, `0` = discrete.
3. **Platform class** — Darwin + arm64 = unified (Apple Silicon); Linux + aarch64 with Tegra device-tree markers = unified (Jetson).
4. **AMD APU carve-out** — an AMD display-class PCI device with ≤ 1 GiB `mem_info_vram_total` = unified.
5. **Fallback** — nothing matched: unknown, with an explicit reason.

Every memory figure carries a provenance string identifying its source (for example `nvml`, `torch.cuda.mem_get_info`, `psutil.virtual_memory`, `tegra-device-tree`). An unknown verdict is never promoted to unified.

## Per-platform notes

### Jetson (Tegra)

- aarch64 with unified memory; Xavier is `sm_72`, Orin is `sm_87` and can be reached via same-major `sm_80` SASS on cu130/cu132.
- JetPack 7 (CUDA 13.x) resolves to a cu13x index and runs the GPU-vs-CPU numerical self-test; with `--research` it resolves to cu130 because cu132 publishes no torchaudio wheels.
- JetPack 6 (CUDA 12.6) resolves to the CPU index with a note naming Python 3.12 and the manual `--index-url` override.
- Orin Nano Super (JetPack 7.2, CUDA 13.2, `sm_87`, unified) resolves to cu132 torch 2.14.0 via same-major `sm_80` SASS with the self-test; with `--research`, cu130 torch 2.14.0 plus torchaudio 2.11.0.
- Operators can pass `--index-url` with a JetPack-appropriate wheel URL, or build torch from source.

### AMD APU

- Discrete-looking to the amdgpu driver, but VRAM is a carve-out of ≤ 1 GiB.
- Classified as unified by the carve-out heuristic (detection ladder step 4).
- The preflight gate applies its threshold to system memory, not to the tiny carve-out.

### Apple Silicon

- Darwin + arm64; MPS backend.
- Memory is always unified.
- Uses the default PyPI torch wheel — no `--index-url` needed.
- Selected with the `--mps` flag or auto-detected.

## Diagnostics

Dump the probed host description:

```bash
.venv/bin/python -c "from kaine.hardware import describe_host; import json; print(json.dumps(describe_host(), indent=2))"
```

Run the wheel-index resolver standalone (the same entry point `install.sh` calls):

```bash
.venv/bin/python -m kaine.wheel_index
```
