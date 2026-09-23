## Why

The installers choose a PyTorch wheel index from the host (`kaine.wheel_index`), but nothing checks that the chosen index actually carries a torch that satisfies the project's torch requirement in `pyproject.toml` (currently `torch>=2.14.0,<3`). Querying download.pytorch.org on 2026-09-22 gives these newest torch versions per index:

| Index | Newest torch |
| --- | --- |
| cu118 | 2.7.1 |
| cu121 | 2.5.1 |
| cu126 | 2.14.0 |
| cu128 | 2.11.0 |
| cu129 | 2.13.0 |
| cu130 | 2.14.0 |
| cu132 | 2.14.0 |
| rocm6.2 (fixed ROCm index) | 2.5.1 |
| rocm7.1 | 2.13.0 |
| rocm7.2 | 2.14.0 |
| xpu, cpu | 2.14.0 |

So decision-table rows 2, 4, 5 and 8 (CUDA 12.8–12.9, 12.1–12.4 and 11.8–12.0 drivers) and the whole ROCm flavor resolve to indexes that cannot install the project at all. The failure appears only when pip runs. The container image build already hit it.

Two more fit problems block the hardware the project targets:

- **JetPack 7 on Jetson Orin.** Row 10 sends every unified-memory aarch64 host to the CPU index. On JetPack 7.2 (CUDA 13.2, SBSA toolkit), NVIDIA verifies that upstream `cu13x` aarch64 wheels run on Orin, and the CPU route throws away the GPU.
- **The tier recommender ignores memory on accelerator hosts.** `kaine.hardware` returns Tier 2 (workstation) for any host with one accelerator, including an 8 GB unified Jetson, and nothing calls it from the installer or the first-run wizard.

## What Changes

- **Floor-aware index selection.** The resolver reads the torch floor from `pyproject.toml` and holds a maintained table of the newest torch per index. A row whose index cannot satisfy the floor falls back to the newest index that can, among those the host driver can run (for example, a 12.8 driver resolves to cu126). When no CUDA index works with the driver, the resolver chooses CPU with a warning that names the floor and the driver. A networked check (`python -m kaine.wheel_index --verify-indexes`) refreshes the table from download.pytorch.org, run manually and not in the offline suite.
- **ROCm from the same table.** The ROCm flavor uses the newest ROCm index that carries the floor, and warns that hosts on older ROCm stacks need an older floor.
- **JetPack 7 GPU path.** A unified aarch64 host whose driver reports CUDA 13.0 or newer resolves to the newest `cu13x` index carrying the floor. The warning notes that Orin (sm_87) runs sm_80-compatible kernels and that some models have produced NaNs. JetPack 6 (CUDA 12.6, Python 3.10) keeps the CPU route, with a note naming the Python 3.12 requirement and the jetson-ai-lab wheel index for manual override.
- **Memory-aware tier recommendation, wired into setup.** The recommender budgets by system RAM on unified hosts and by the smaller of RAM and VRAM on discrete hosts. An 8 GB unified host is recommended Tier 1. The first-run wizard shows the recommendation and applies the matching profile only when the operator confirms.
- **Torch floor policy (open question for the operator).** Every raise of the floor removes hosts. The proposal asks the operator to set the floor to the lowest version the code needs and to stop Dependabot raising it automatically (an `ignore` rule for `torch` in `.github/dependabot.yml`). The floor-aware resolver is correct whatever floor is chosen.

## Capabilities

### New Capabilities
- (none)

### Modified Capabilities
- `dynamic-hardware`: floor-aware wheel-index resolution, ROCm index selection, JetPack 7 GPU path.
- `deployment-tiers`: memory-aware tier recommendation surfaced in the first-run wizard.

## Impact

- `kaine/wheel_index.py`, `scripts/install.sh`, `scripts/install.py`, `kaine/hardware.py`, `kaine/setup/wizard.py`
- `docs/accelerator-provisioning.md`, `docs/deployment-tiers.md`
- `tests/test_wheel_index.py` and golden fixtures, `tests/test_hardware*.py`, `tests/test_setup_wizard.py`
- No entity boot is needed to verify this change.
