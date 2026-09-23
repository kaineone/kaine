## Context

`kaine/wheel_index.py` holds `DECISION_TABLE` (ordered rows keyed on architecture, driver CUDA version and unified memory) and `INDEX_ARCH_MAP` (per-index GPU architecture coverage). It is standard-library-only so the installers can run it before any dependency is installed. `torch-stack-coherence` (#152) already makes the installers read the torch spec from `pyproject.toml`, install torch and torchvision together, and pin the result in `<venv>/kaine-torch-constraints.txt`.

## Decisions

1. **Tested range, exact pin.** The project declares a range the suite has passed at both ends (`>=2.9.1,<2.15`: 2.9.1 CPU and 2.14.0 cu130 on 2026-09-22). The resolver chooses one exact version per host, so the architecture check applies to the version actually installed.
2. **Coverage is version-specific.** `INDEX_ARCH_MAP` becomes keyed by (index, torch minor version). Entries are recorded from the real wheels (`torch.cuda.get_arch_list()`), never from memory.
3. **Fallback direction.** A newer driver runs older CUDA builds (driver forward compatibility). The resolver walks from the newest index the driver supports downwards, and stops at the first index whose in-range torch covers the device.
4. **Jetson safety.** Running sm_80 cubins on sm_87 is binary-compatible, but the reported NaNs make "installs and imports" insufficient evidence. A numerical self-test (matmul and conv in fp16/bf16 against a CPU reference, bounded relative error, no NaN or Inf) decides whether the GPU path is kept.
5. **Tiers follow residency, not capability cuts.** An 8 GB Orin keeps its GPU. Module residency schedules what is resident in memory, and the tier profile does not remove faculties.
6. **Floor policy.** Automatic floor raises remove hosts silently. Bumps are deliberate and tested (see proposal).

## Risks

- **The published-versions table goes stale.** `--verify-indexes` and the tested-hosts table make the drift visible. The resolver never selects an index whose recorded versions miss the range.
- **The self-test adds install time.** It is bounded to a few seconds and runs only on unified aarch64 CUDA hosts.
