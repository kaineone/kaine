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

## Decision 3: gpu-preflight three memory states

The gate consumes `classification` plus pools. `known-discrete` preserves today's behaviour exactly (refuse when free VRAM < `min_free_vram_gb`). `known-unified` applies the same configured threshold to **available** system memory (`MemAvailable`, i.e. reclaimable — not bare free). `unknown` passes and annotates; unknowable memory never refuses boot on its own, though all other independent gates still apply.

## Decision 4: override and precedence semantics

Precedence, highest first:

1. `--index-url <url>` — operator override of the resolved URL; beats all probes; used verbatim; never silently falls back.
2. Force flags `--cpu --cuda --rocm --xpu --mps` — beat auto-detection for **variant** selection; exact existing semantics; mutually exclusive as today.
3. Host-aware decision table — resolves the URL for the selected variant when no `--index-url` is given (`--cpu`/`--rocm`/`--xpu`/`--mps` keep their existing fixed indexes; only the CUDA variant is table-resolved).
4. CPU index + warning — terminal fallback of the ladder.

Combination rules: `--index-url` + force flag → flag picks the variant, override picks the URL. `--index-url` alone → variant auto-detected, URL forced. A forced CUDA variant for which the table yields no candidate (unified Tegra) aborts with guidance rather than installing a known-incompatible wheel.

## Decision 5: wizard mismatch detection and consented corrective install

The first-run wizard compares the installed runtime against the probed host: driver CUDA capability vs `torch.version.cuda` (mismatch when torch requires a newer driver than the host provides, i.e. torch major > driver major, or equal majors with torch minor > driver minor — torch older than the driver is fine), and each device's compute capability vs `torch.cuda.get_arch_list()` PTX-aware (satisfied iff the list contains exact `sm_XY`, or any `sm_ZW+PTX` / `compute_ZW` entry with `(Z,W) ≥ (X,Y)`). On mismatch it presents both sides of the finding, proposes the corrective reinstall (re-running `scripts/install.sh` with the table-resolved URL passed explicitly as `--index-url`, so the corrective path is auditable), and proceeds only on explicit affirmative consent with decline as the default; a decline persists an annotation and does not re-prompt in the same boot; a failed corrective install surfaces the installer output unmasked.

## Decision 6: non-regression guard

The dual-GPU x86_64 NVIDIA workstation default, ROCm, XPU, MPS, and CPU-only paths are pinned by requirement: same variant, same index URLs, same detection order, same gate messages, and no new interactive prompts on hosts where the installed accelerator already matches the probed host.

## Risks / Trade-offs

- `INDEX_ARCH_MAP` can drift from upstream wheel contents; it is a versioned data constant, unknown index names never match (safe fall-through), and updates ride the normal release process.
- The conservative `index ≤ driver CUDA` rule may pick older wheels than CUDA minor-version compatibility would allow; correctness at first kernel launch is preferred over newest-feature access, and `--index-url` exists for operators who disagree.
- PTX-only selections incur JIT latency on first launch; this is annotated, not blocked.
- Tegra operators must supply a JetPack-provided index via `--index-url`; the ladder warning and the `--cuda` abort error both say so explicitly.

Normative requirements and scenarios for this change live in `openspec/changes/host-aware-accelerator-provisioning/specs/`.