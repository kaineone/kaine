## 1. Merger
- [x] 1.1 `kaine/lifecycle/adapter_merge.py`: an `AbliterationScorer` protocol beside `CapabilityEval` (async `score(model, tokenizer)` returning an object with `passed`, `failed_probe`, `matched_pattern`); `TiesDareAdapterMerger(..., abliteration_scorer=None)`.
- [x] 1.2 The check runs capability eval on each parent and the merged adapter and the abliteration scorer on the merged adapter, releasing each loaded model before the next load; any absence or exception rejects with the reason.
- [x] 1.3 `peft_model_loader(base_model_path)` returns a callable `adapter_path -> (model, tokenizer)` (PEFT on the base model, imports deferred to call time).
- [x] 1.4 `kaine/lifecycle/manager.py`: `merger_from_name(..., merge_checks=None)` wires the factory's results and the loader into the real merger only; the probe paths are read by the factory.
- [x] 1.5 `ForkManager.merge` refuses on skipped (both parents with adapters), rejected or failed, unless `allow_unmerged_adapters`; the error message names the reason.

## 2. Nexus
- [x] 2.1 `kaine/nexus/__main__.py` `_build_fork_manager` passes a factory that imports and builds `LocalProbeSetCapabilityEval` and `AbliterationProbeScorer` from the two new keys.
- [x] 2.2 `kaine/nexus/diagnostics.py`: the merge handler awaits `asyncio.to_thread(fork_manager.merge, ...)`.

## 3. Config
- [x] 3.1 `config/kaine.toml` `[lifecycle.adapter_merge]`: `capability_probe_path = ""`, `abliteration_probe_path = ""` with comments.

## 4. Tests
- [x] 4.1 Veto: reject on capability drop; accept on small drop with a passing verdict; reject on abliteration failure; reject with no evaluator / no scorer / no loader; reject when the loader or a check raises (replaces `test_eval_failure_accepts_merge`).
- [x] 4.2 Existing successful-merge tests inject a passing evaluator, scorer and loader.
- [x] 4.3 `ForkManager.merge` with a merger reporting rejected, and one reporting failed: raises, and no snapshot directory is added; with `allow_unmerged_adapters=True` the snapshot metadata records the reason.
- [x] 4.4 `merger_from_name`: factory called for the real merger (holds evaluator, scorer, loader) and not called for the fake one.
- [x] 4.5 Nexus: a merge whose checks run `asyncio.run` succeeds through `POST /diagnostics/merges` (proves the handler is off the loop); a rejected merge answers 409.

## 5. Docs
- [x] 5.1 `docs/12-forks-and-merges.md`, `kaine/lifecycle/ADAPTER_MERGING.md`, the configuration appendix's `[lifecycle.adapter_merge]` table, and `docs/05-nexus.md` where it describes merge refusals.

## 6. Second-review fixes
- [x] 6.1 An empty or missing capability probe set rejects (`LocalProbeSetCapabilityEval(require_probes=True)` in the Nexus factory; Hypnos's default unchanged); scores outside [0, 1] reject.
- [x] 6.2 All scoring and verdict handling sit inside the check's `try`; `merge()` removes the merged directory on any exit from the checks other than keeping it, `BaseException` included.
- [x] 6.3 Merged-adapter directories carry a random suffix after the timestamp.
- [x] 6.4 `capability_loss_threshold` is validated to lie in [0, 1).
- [x] 6.5 Tests for each, in `tests/test_merge_veto_review_fixes.py`.
