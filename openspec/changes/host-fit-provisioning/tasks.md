## 1. Range and pin

- [x] 1.1 `pyproject.toml`: `torch>=2.9.1,<2.15`; Dependabot `ignore` for torch, torchvision, torchaudio.
- [ ] 1.2 `kaine.wheel_index`: stdlib specifier check; dated published-versions table per (index, arch); choose the newest in-range version on the newest driver-compatible index with coverage; emit an exact `torch==` plus matching companions into the constraints file.
- [ ] 1.3 `INDEX_ARCH_MAP` keyed by (index, torch minor), recorded from real wheels; same-major SASS rule.
- [ ] 1.4 `--verify-indexes` networked refresh and diff.

## 2. ROCm and Jetson

- [ ] 2.1 ROCm resolution in `kaine.wheel_index` (ROCm version and gfx probe); both installers call it; clear refusal for stacks older than any in-range index.
- [ ] 2.2 Unified aarch64 with driver CUDA ≥ 13.0: resolve cu13x with the unified exception; JetPack 6 keeps CPU with the note.
- [ ] 2.3 Post-install fp16/bf16 GPU-vs-CPU self-test on unified CUDA hosts; fall back to CPU wheels on failure.

## 3. Tier fit

- [ ] 3.1 Memory-aware `recommend_tier` with the numeric thresholds in the spec.
- [ ] 3.2 Wizard shows the recommendation and applies the profile only on confirmation.

## 4. Verification and docs

- [ ] 4.1 Update the decision table and add the tested-hosts table in `docs/accelerator-provisioning.md`; update `docs/deployment-tiers.md`.
- [ ] 4.2 Golden fixtures regenerated; offline suite green at both ends of the torch range on the CPU index.
- [ ] 4.3 `openspec validate host-fit-provisioning --strict` passes.
