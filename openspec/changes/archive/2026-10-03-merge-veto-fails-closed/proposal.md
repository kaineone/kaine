# A merged adapter is checked before it is kept, and an unchecked merge is refused

## Why
`TiesDareAdapterMerger` was built with a capability-loss veto, but nothing ever gives it the evaluator and model loader the veto needs. `merger_from_name` constructs it with the config alone, so the veto returns early on every merge and `[lifecycle.adapter_merge].capability_loss_threshold` has no effect. When an evaluator is present and raises, the veto logs the exception and accepts the merge (`test_eval_failure_accepts_merge` pins that). Either way a merged adapter reaches the merged snapshot without any check.

Three more defects sit on the same path:
- A merge the veto rejects, or one whose PEFT backend fails, still produces a merged snapshot. `ForkManager.merge` refuses only when the merger reports `adapter_merge_skipped`, not `adapter_merge_rejected` or `adapter_merge_failed`, so the snapshot holds the parents' adapters uncombined while claiming to be a merge: the pretend process the skipped-merge refusal exists to prevent.
- The veto calls `asyncio.run`, and Nexus calls the synchronous `ForkManager.merge` directly inside its async request handler. On that thread a loop is already running, so `asyncio.run` raises; the veto would catch that and accept.
- Hypnos never promotes a trained adapter without the welfare-load-bearing abliteration veto (no refusal conditioning re-introduced through training). A TIES/DARE merge changes the organ's weights just as training does, yet a merged adapter gets no abliteration check at all.

Research impact: none. Studies do not merge forks, and the running module-ignition study uses a pinned image.

## What changes
- **Checks on every merged adapter.** After a successful backend merge, `TiesDareAdapterMerger` loads each parent adapter and the merged adapter on the base model, runs the capability evaluator on all of them and the abliteration scorer on the merged adapter, and keeps the merge only when the capability loss is within `capability_loss_threshold` AND the abliteration verdict passes. Each loaded model is released before the next load.
- **Fail closed.** No evaluator, no scorer, no model loader, an empty or missing probe set (`LocalProbeSetCapabilityEval(require_probes=True)`; the Hypnos default is unchanged), a score that is not a finite number in [0, 1], or any exception during the checks rejects the merge (`adapter_merge_rejected` with the reason) and removes the merged directory. `capability_loss_threshold` must lie in [0, 1), so no configuration skips the checks.
- **No collisions.** Merged-adapter directories get a random suffix after the timestamp, since concurrent merges can start in the same second.
- **Wiring.** `adapter_merge.peft_model_loader(base_model_path)` loads an adapter onto the base model with PEFT. `merger_from_name` takes a `merge_checks` factory, called only when the real merger is built, that returns the capability evaluator and abliteration scorer; the model loader comes from `base_model_path`. Nexus, the only merge caller, passes a factory that builds Hypnos's `LocalProbeSetCapabilityEval` and `AbliterationProbeScorer` from two new keys, `[lifecycle.adapter_merge].capability_probe_path` and `abliteration_probe_path` (empty = the bundled probe sets, as in `[hypnos.voice_alignment]`). The lifecycle layer still does not import `kaine.modules`; the composition root does.
- **No snapshot from a refused merge.** `ForkManager.merge` raises `UnmergedAdaptersError` (Nexus: 409) when the merger reports skipped (both parents with adapters, as now), rejected, or failed, and writes nothing. `allow_unmerged_adapters=True` still lets an operator keep the parents' adapters uncombined, never the rejected merged adapter, and the snapshot metadata records why.
- **Off the event loop.** Nexus runs `ForkManager.merge` in a worker thread.
- `test_eval_failure_accepts_merge` becomes a test that the merge is rejected.

The cycle process also builds a `ForkManager` without the adapter-merge config, but it only snapshots and forks; it never merges, so it is left alone.
