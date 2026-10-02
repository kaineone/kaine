## 1. Fixes
- [x] 1.1 Divergence observer: outcome fields from `voice_alignment`, metrics from the top level; skip when the summary's `voice_alignment` phase result has `metadata.skipped`.
- [x] 1.2 `EvaluationConfig.from_mapping` reads `oscillatory_ablation`.
- [x] 1.3 Correct the `lingua.out` comment in `raw_bus_archive_consumer.py`.

## 2. Tests
- [x] 2.1 A real Hypnos-shaped `hypnos.sleep.completed` summary (built with the same keys `Hypnos` emits) yields a record with non-null metrics and the outcome fields.
- [x] 2.2 A gate-skipped summary (`config disabled`) yields no record; a no-pairs summary yields one with `reason` set and `samples_used = 0`.
- [x] 2.3 `[evaluation].oscillatory_ablation = true` enables the ablation recorder in the sidecar registry; absent leaves it off.
- [x] 2.4 Mutation-check: the old sub-dictionary reads make 2.1 fail.

## 3. Docs
- [x] 3.1 Update the research-data chapter and the configuration appendix.
