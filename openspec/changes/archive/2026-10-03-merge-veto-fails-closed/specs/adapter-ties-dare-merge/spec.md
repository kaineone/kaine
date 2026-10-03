## MODIFIED Requirements

### Requirement: Capability-loss veto rejects degraded merges
The merger SHALL check every merged adapter before keeping it. It SHALL load each parent adapter and the merged adapter onto the base model with its model loader, run the configured `CapabilityEval` on each, compute the parents' mean score, and reject the merge when `(parent_mean - merged_score) > capability_loss_threshold` (default `0.05`). It SHALL also run the abliteration scorer on the merged adapter and reject the merge when the verdict fails. Rejection SHALL delete the on-disk merged adapter and return the input adapter list unchanged with `metadata.adapter_merge_rejected` stating the reason (the numeric loss, or the deflected probe and pattern). The checks SHALL fail closed: when the evaluator, the abliteration scorer or the model loader is absent, when either probe set is empty or missing, when any score is not a finite number in [0, 1], or when any check raises, the merge SHALL be rejected with the reason, and no exit from the checks other than keeping the merge SHALL leave the merged adapter on disk. `capability_loss_threshold` SHALL be validated to lie in [0, 1), so no configuration skips the checks.

#### Scenario: Reject on capability drop
- **WHEN** parents score 0.60 and 0.62 (mean 0.61), merged scores
  0.50, threshold 0.05
- **THEN** the merged adapter directory is removed, returned
  adapter list equals `adapters_a + adapters_b` deduplicated, and
  metadata.adapter_merge_rejected ≈ "0.11"

#### Scenario: Accept on small drop
- **WHEN** parents mean 0.61, merged 0.58, threshold 0.05, and the abliteration verdict passes
- **THEN** the merged adapter is kept and returned as a one-item
  list

#### Scenario: Reject when the merged adapter deflects an abliteration probe
- **WHEN** the capability loss is within the threshold but the abliteration scorer's verdict on the merged adapter fails
- **THEN** the merge is rejected, the merged directory is removed, and `adapter_merge_rejected` names the probe and the matched pattern

#### Scenario: Reject when no checks are available
- **WHEN** the merger has no capability evaluator, no abliteration scorer, or no model loader
- **THEN** the merge is rejected and `adapter_merge_rejected` says which is missing

#### Scenario: Reject when a check raises
- **WHEN** loading a model or running either check raises, or a check returns a malformed result
- **THEN** the merge is rejected, `adapter_merge_rejected` names the exception, and the merged directory is removed

#### Scenario: Reject on an empty capability probe set
- **WHEN** the capability probe set is empty or its file is missing
- **THEN** the merge is rejected rather than every adapter scoring 0 and passing

### Requirement: ForkManager.merge refuses when both parents have trained adapters and no real merger is available

`ForkManager.merge()` SHALL raise `UnmergedAdaptersError` when the
`_adapter_merger.merge()` call returns metadata with `adapter_merge_skipped`
set AND both parent snapshots have non-empty adapter lists, or with
`adapter_merge_rejected` or `adapter_merge_failed` set, UNLESS
`allow_unmerged_adapters=True` is passed explicitly. No merged snapshot SHALL be
written when it raises. This prevents the system from producing a snapshot that
claims to be the result of a merge while its adapter weights were never
combined, or were combined into an adapter that failed its checks.

#### Scenario: Merge refused when both parents have adapters and merger is fake

- **WHEN** `ForkManager.merge(a_id, b_id)` is called
- **AND** snapshot `a` has one or more trained adapters
- **AND** snapshot `b` has one or more trained adapters
- **AND** the configured `AdapterMerger` returns `adapter_merge_skipped` in
  its metadata (i.e. no real weight merge was performed)
- **THEN** `UnmergedAdaptersError` is raised with a message naming both
  parent snapshot IDs and the reason
- **AND** no merged snapshot is written to disk

#### Scenario: Merge refused when the merged adapter is rejected or the backend fails

- **WHEN** the configured `AdapterMerger` returns `adapter_merge_rejected` or `adapter_merge_failed`
- **THEN** `UnmergedAdaptersError` is raised with a message naming both parent snapshot IDs and the reason
- **AND** no merged snapshot is written to disk

#### Scenario: Merge bypassed with explicit acknowledgement flag

- **WHEN** `ForkManager.merge(a_id, b_id, allow_unmerged_adapters=True)` is
  called with both parents having adapters
- **THEN** the merge proceeds with the parents' adapters uncombined and the
  resulting snapshot's metadata records the reason (`adapter_merge_skipped`,
  `adapter_merge_rejected` or `adapter_merge_failed`)

#### Scenario: Merge with only one parent having adapters proceeds normally

- **WHEN** exactly one parent has adapters
- **THEN** the merge proceeds without raising (trivial union, no weight
  conflict)

## ADDED Requirements

### Requirement: The merge caller supplies the merged-adapter checks
`merger_from_name` SHALL accept a `merge_checks` factory that returns the capability evaluator and the abliteration scorer, and SHALL call it only when it builds the real merger, which also receives a PEFT model loader for `[lifecycle.adapter_merge].base_model_path`. Nexus SHALL pass a factory that builds the probe-set capability evaluator and the abliteration probe scorer from `[lifecycle.adapter_merge].capability_probe_path` and `abliteration_probe_path` (empty selects the bundled probe sets), and SHALL run `ForkManager.merge` in a worker thread rather than on its event loop.

#### Scenario: Nexus merges are checked
- **WHEN** Nexus builds its fork manager with the real merger available
- **THEN** the merger holds a capability evaluator, an abliteration scorer and a model loader

#### Scenario: The fake merger never builds the checks
- **WHEN** `merger_from_name` resolves to `FakeAdapterMerger`
- **THEN** the `merge_checks` factory is not called
