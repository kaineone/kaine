<!-- SPDX-License-Identifier: LicenseRef-CAL-0.2 -->
<!-- Copyright (c) 2026 Kaine.One <kaine.one@tuta.com> -->

# Accelerator Provisioning

KAINE auto-detects accelerator hardware at install time and at boot time. The installer resolves the correct PyTorch wheel index from probed host properties, and the pre-boot memory gate verifies that the accelerator has headroom before any module initializes. This page documents both mechanisms for operators.

## CUDA wheel index resolution

`scripts/install.sh` resolves the CUDA wheel index at install time by invoking `python -m kaine.wheel_index`. The resolver probes four host properties:

- CPU architecture (`uname`)
- driver CUDA version (the `nvidia-smi` header)
- compute capability of every probed GPU (`nvidia-smi --query-gpu=compute_cap`)
- unified-memory state (`kaine.hostmem`)

It then walks the decision table below to pick the correct PyTorch wheel index. The resolver is advisory: if probing fails, `install.sh` uses its legacy fallback. Every decision — probe results, matched row, resolved index — is logged.

### Decision table

The table below is the authoritative rendering of `kaine.wheel_index.DECISION_TABLE`. Rows are evaluated top-to-bottom; the first match wins. The resolver first filters the candidate indexes to those whose CUDA version is less than or equal to the host driver's CUDA version, then picks the newest driver-compatible index that publishes an in-range `torch` covering every probed GPU.

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

Rows with a CC guard require every probed GPU's compute capability to have either an exact `sm_XX` entry, a same-major SASS entry that is ≤ the device's minor version, or a compatible PTX entry (`compute_XX` with XX ≥ device SM) in `INDEX_ARCH_MAP`. `INDEX_ARCH_MAP` records, per index URL, which architectures and SM variants that index covers. Rows with `Warning` = yes resolve to the CPU index and surface a warning at install time.

The tested `torch` range is declared in `pyproject.toml` (currently `>=2.9.1,<2.15`). It is a *bounded tested range*: the offline suite runs in CI at both ends of the range on the CPU index (the newest in-range torch, and the range's lower bound), accelerator hosts are verified manually and recorded in the Tested hosts table, Dependabot does not raise this bound automatically, and widening the range needs the CI job at both new ends plus a recorded smoke test on each accelerator family the change affects. Not every intermediate point is exercised.

When a CUDA index is selected, the resolver records the exact `torch`, `torchvision`, and `torchaudio` versions that match the selected index and installs those exact versions. The installer writes those exact versions into a constraints file so that later `pip install` calls cannot silently float to a different torch build.

Data provenance for the ladder lives in `kaine/wheel_data.py`, which records the published versions and architecture lists for each index (dated). Drift against the live indexes is reported by `python -m kaine.wheel_index --verify-indexes`.

The research install path (`scripts/install.sh --research`) passes `--need-torchaudio` to the resolver. Because the cu132 index publishes no `torchaudio` wheels, hosts that would otherwise resolve to cu132 instead resolve to cu130 so that `torchaudio` is available.

### ROCm wheel index resolution

AMD hosts are resolved from the host ROCm version (read from `/opt/rocm/.info/version`, or overridden with `KAINE_ROCM_VERSION`) and the GFX targets (from `rocminfo`, or overridden with `KAINE_ROCM_GFX`). The resolver selects the newest ROCm wheel index whose version is ≤ the host ROCm version, publishes an in-range `torch` for the host architecture, and covers every listed GFX target. When no in-range ROCm index fits, the resolver refuses with a clear message instead of silently falling back to CUDA wheels.

### Jetson handling

Jetson hosts appear as aarch64 with unified memory.

- JetPack 7 (driver CUDA ≥ 13.0) resolves to a cu13x wheel index and runs a GPU-vs-CPU numerical self-test (`python -m kaine.accel_selftest`). If the self-test fails, the installer automatically falls back to CPU wheels.
- JetPack 6 (driver CUDA < 13.0) resolves to CPU wheels with a note that a JetPack-provided CUDA wheel index is required. Python 3.12 is required for the upstream CPU wheels.

### Unified-memory note for non-aarch64 hosts

Unified-memory evidence is ignored for CUDA on non-aarch64 hosts: NVIDIA unified-memory GPUs are aarch64-only. If a non-aarch64 host reports unified memory, the resolver treats it as discrete for the CUDA ladder (the evidence likely comes from a non-NVIDIA integrated GPU).

### Tested hosts

| Host | Accelerator | Index | torch | Verified |
|------|-------------|-------|-------|----------|
| Development workstation (x86_64) | RTX 4070 SUPER + RTX 3070, driver CUDA 13.x | cu130/cu132 | 2.14.0 | offline suite 2026-09-22 |
| CPU (x86_64) | none | cpu | 2.9.1 and 2.14.0 | offline suite 2026-09-22 |

Other rows are added when a host is verified.

### Operator override: `--index-url`

`--index-url <URL>` on `install.sh` overrides the resolved CUDA wheel index. Precedence, highest first:

1. Operator override (`--index-url`)
2. Decision table
3. Terminal CPU fallback

Only the cuda flavor consults the table. The `--cpu`, `--xpu`, and `--mps` flavors use fixed indexes; `--rocm` is resolved from the host ROCm version and GFX targets (see above); only the `cuda` flavor accepts `--index-url`.

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

- aarch64 with unified memory; Xavier is `sm_72`, Orin is `sm_87`.
- No upstream CUDA wheel index ships Tegra SASS, so the resolver lands on the CPU index with a JetPack pointer (decision table row 10).
- NVIDIA ships Jetson PyTorch wheels through forums.developer.nvidia.com, outside the standard pip indices.
- Operators should pass `--index-url` with the JetPack-appropriate wheel URL, or build torch from source.
- JetPack 6.x ships CUDA 12.6; JetPack 7.x ships CUDA 13.2.

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
