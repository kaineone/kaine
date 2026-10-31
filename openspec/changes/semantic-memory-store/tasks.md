## 1. Design (this change)

- [x] 1.1 Record the promotion criterion, the gist, slow update, strength, retrieval and rendering, lifecycle, the checks before any entity run, and the estimate.

## 2. Start condition

- [ ] 2.1 **Deferred:** the first module-addition study has finished and `episodic-recall-content` has merged.

## 3. Promotion and gist (PR 1)

- [ ] 3.1 `kaine/modules/episodic_memory/semantic.py`: promotion criterion, gist, merge rule
- [ ] 3.2 Entries on the module's log gain; protection in the promoting sleep; downscaling and pruning with traces
- [ ] 3.3 Phase 3 order: `associate()`, `promote_semantic()`, `prune()`; prune also when promotion fails; content-free summary counts
- [ ] 3.4 Config keys under `[episodic_memory.semantic]`: `enabled = false`, `min_wakes = 3`, `min_share = 0.5`, `sim_merge = 0.9`, `max_members = 64`
- [ ] 3.5 Tests: `tests/test_semantic_promotion.py` (three wakes promoted, one wake not, traces without members not promoted); `tests/test_semantic_gist.py` (shares, medians, affect mean, no text or own words, member bound); `tests/test_semantic_merge.py`; `tests/test_semantic_strength.py` (protected when promoted, downscaled otherwise, pruned at the floor); `tests/test_sleep_phase3_semantic_order.py`
- [ ] 3.6 Worker first-pass review, lead review, independent second review

## 4. Retrieval and rendering (PR 2)

- [ ] 4.1 Live recall over the semantic collection; `content.kind = "semantic"`
- [ ] 4.2 Felt rendering with frequency words; digit guard
- [ ] 4.3 Tests: `tests/test_semantic_recall.py`; `tests/test_felt_semantic_recall.py` (frame, frequency bins, no "I remember", no digits)
- [ ] 4.4 Worker first-pass review, lead review, independent second review

## 5. Lifecycle, records and docs (PR 3)

- [ ] 5.1 Tests: `tests/test_semantic_lifecycle.py` (preservation export, revive with strengths relative to the restored log gain, decommission backup and deletion, fork copy when memory is copied)
- [ ] 5.2 Research-log counts per run: entries, share with a negative affect mean, share of recalls that were semantic (content-free)
- [ ] 5.3 Docs: episodic memory chapter (the semantic collection no longer reserved), sleep chapter (phase 3), faithful renderer chapter, configuration appendix; paper notes for §4, A.10, Table A1 and §9 in the paper's revision notes
- [ ] 5.4 Worker first-pass review, lead review, independent second review

## 6. Before any entity run with the store on

- [ ] 6.1 Entity-free scripted multi-wake run: a planted recurring pattern is promoted with the right kinds and a non-recurring control is not; share of entries whose member traces share a film item or own-speech content; recorded under `docs/records/`
- [ ] 6.2 Same run with negative affect planted on half the pattern's episodes: semantic recalls with a negative affect mean exceed the episodes' negative share by at most 10 points
- [ ] 6.3 Equivalence bounds for the entry counts and negative-valence share written into the study's preregistration before its pilots
