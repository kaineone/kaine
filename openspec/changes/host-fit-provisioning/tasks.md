## 1. Floor-aware resolution

- [ ] 1.1 Add `INDEX_TORCH_MAX` (newest torch per index, dated) and read the torch floor from `pyproject.toml` in `kaine.wheel_index`.
- [ ] 1.2 When a matched row's index cannot satisfy the floor, fall back to the newest driver-compatible index that can; otherwise resolve CPU with a warning naming floor and driver.
- [ ] 1.3 Add `--verify-indexes` (networked, manual) that queries each index and reports drift from `INDEX_TORCH_MAX`.
- [ ] 1.4 Update golden fixtures and `docs/accelerator-provisioning.md` (decision table and fallback rule).

## 2. ROCm and Jetson

- [ ] 2.1 Choose the ROCm index from the table (newest ROCm index carrying the floor) in both installers; warn about older ROCm stacks.
- [ ] 2.2 Unified aarch64 with driver CUDA ≥ 13.0 resolves to the newest `cu13x` index carrying the floor, with the sm_87 warning; JetPack 6 keeps the CPU route with the Python 3.12 and jetson-ai-lab note.
- [ ] 2.3 Add sm_87 coverage notes to `INDEX_ARCH_MAP` for the cu13x aarch64 entries (compatible kernels, not native).

## 3. Tier fit

- [ ] 3.1 Make `recommend_tier` memory-aware (unified: system RAM; discrete: min(RAM, VRAM)); 8 GB unified → Tier 1.
- [ ] 3.2 Show the recommendation in the first-run wizard and apply the profile only on operator confirmation.

## 4. Verification

- [ ] 4.1 Offline suite green; `openspec validate host-fit-provisioning --strict` passes.
- [ ] 4.2 Record the operator's floor-policy decision in `design.md` and, if chosen, add the Dependabot ignore rule.
