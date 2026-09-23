## Why

The installers pick a PyTorch wheel index from the host (`kaine.wheel_index`), but nothing checks that the chosen index publishes a torch the project accepts, or that the torch version pip then installs has kernels for the host GPU. `pyproject.toml` requires `torch>=2.14.0,<3`, a floor raised automatically by Dependabot. Querying download.pytorch.org on 2026-09-22 gives these newest torch versions per index:

| Index | Newest torch | Index | Newest torch |
| --- | --- | --- | --- |
| cu118 | 2.7.1 | rocm6.2 (hard-coded today) | 2.5.1 |
| cu121 | 2.5.1 | rocm6.3 / rocm6.4 | 2.9.1 |
| cu126 | 2.14.0 | rocm7.0 | 2.10.0 |
| cu128 | 2.11.0 | rocm7.1 | 2.13.0 |
| cu129 | 2.13.0 | rocm7.2 | 2.14.0 |
| cu130 / cu132 | 2.14.0 | cpu / xpu | 2.14.0 |

Decision-table rows 2, 4, 5 and 8 and the whole ROCm flavor resolve to indexes that cannot install KAINE; the failure only shows when pip runs. Two related problems block hardware the project targets:

- **JetPack 7 on Jetson Orin.** Row 10 sends every unified-memory aarch64 host to the CPU index. On JetPack 7.2 (CUDA 13.2, SBSA toolkit), NVIDIA staff report that upstream `cu13x` aarch64 wheels run on Orin. But the repo's own `INDEX_ARCH_MAP` lists `cu130` aarch64 as sm_90/sm_100/compute_100 only, and there are public reports of NaNs from some models on this path.
- **The tier recommender ignores memory.** `kaine.hardware.recommend_tier` returns Tier 2 for any single-accelerator host, including an 8 GB unified Jetson. Nothing outside tests calls it.

The operator's policy is to **pin torch to a tested version range**. The full offline suite passes on torch 2.9.1 (CPU) and 2.14.0 (cu130), so the tested range is `torch>=2.9.1,<2.15`.

## What Changes

- **Tested torch range.** `pyproject.toml` declares `torch>=2.9.1,<2.15`. A Dependabot `ignore` rule stops automatic bumps of torch, torchvision and torchaudio. Widening the range needs a PR whose CI passes the offline suite at both ends of the range on the CPU index, plus a recorded smoke test per accelerator in a tested-hosts table in `docs/accelerator-provisioning.md`.
- **The resolver pins an exact version.**
  - `kaine.wheel_index` reads the full torch specifier from `pyproject.toml`. It uses a minimal in-module specifier check, because the resolver stays standard-library-only.
  - It holds a dated table of published torch versions per (index, architecture), and chooses the newest version in range on the newest index the driver supports.
  - It checks GPU coverage against an architecture map keyed by (index, torch version), and falls down the driver-compatible indexes only while coverage holds (cu12x keeps sm_70; cu13x drops it).
  - It emits an exact `torch==X.Y.Z` with matching torchvision (and torchaudio for `--research`), which the installers write into the constraints file introduced by `torch-stack-coherence`.
  - `--verify-indexes` (networked, run manually) refreshes and diffs the table.
- **ROCm has one source of truth.** ROCm index selection moves into `kaine.wheel_index`, which probes the `/opt/rocm` version and the gfx target and resolves the newest ROCm index carrying an in-range torch. Hosts on ROCm stacks older than any index in range get a clear refusal naming the requirement.
- **JetPack 7 GPU path with a safety check.**
  - The architecture-ladder rule gains same-major SASS compatibility (an sm_80 cubin runs on sm_86 and sm_87).
  - Unified hosts get an explicit exception, backed by the architecture list recorded from the real wheel (`torch.cuda.get_arch_list()`).
  - After install, a short fp16/bf16 GPU-versus-CPU numerical self-test runs. If it fails, the install falls back to CPU wheels and reports why.
  - JetPack 6 (CUDA 12.6, Python 3.10) keeps the CPU route, with a note naming the Python 3.12 requirement and the manual `--index-url` override.
- **Memory-aware tier recommendation.**
  - The budget is system RAM on unified hosts and the smaller of RAM and VRAM on discrete hosts.
  - Accelerator hosts with a budget of at least 16 GB get Tier 2 (Tier 3 for two or more GPUs).
  - 6–16 GB gets Tier 2 with module residency required, following the budgets in `module-residency-and-speech-tiers`. It never downgrades an Orin to the CPU-only Tier 1 after enabling its GPU.
  - Below 6 GB gets Tier 1.
  - The first-run wizard shows the recommendation and applies the profile only when the operator confirms.

## Capabilities

### New Capabilities
- (none)

### Modified Capabilities
- `dynamic-hardware`: exact, range-aware and coverage-checked wheel selection; ROCm resolution; JetPack 7 path with a numerical self-test; tested torch range.
- `deployment-tiers`: memory-aware tier recommendation in the first-run wizard.

## Impact

- `pyproject.toml`, `.github/dependabot.yml`, `kaine/wheel_index.py`, `scripts/install.sh`, `scripts/install.py`, `kaine/hardware.py`, `kaine/setup/wizard.py`
- `docs/accelerator-provisioning.md` (decision table, tested-hosts table), `docs/deployment-tiers.md`
- `tests/test_wheel_index.py` and golden fixtures, `tests/test_hardware*.py`, `tests/test_setup_wizard.py`, installer tests
- No entity boot is needed to verify this change.
