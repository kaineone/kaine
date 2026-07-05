# adapter-ties-dare-merge Specification

## Purpose
TBD - created by archiving change adapter-ties-dare-merge. Update Purpose after archive.
## Requirements
### Requirement: TiesDareAdapterMerger implements the AdapterMerger protocol
`kaine/lifecycle/adapter_merge.py` SHALL export `TiesDareAdapterMerger`
satisfying the existing `AdapterMerger` protocol. The class SHALL
lazy-import `peft`, `torch`, and `safetensors` inside `merge()`. When
any required import fails, `merge()` SHALL log a warning and
delegate to `FakeAdapterMerger` so existing fork/merge behavior is
preserved.

#### Scenario: Missing extras fall back gracefully
- **WHEN** `peft` is not installed and `TiesDareAdapterMerger.merge`
  is called
- **THEN** the call returns the same shape `FakeAdapterMerger`
  would, with `metadata.adapter_merge_skipped` containing the
  reason and no exception propagated to the caller

### Requirement: Three combination modes supported
The merger SHALL accept `combination_type` of `"ties"`,
`"dare_ties"`, or `"dare_linear"` in its constructor, defaulting to
`"dare_ties"`. The choice SHALL be forwarded to peft's
`model.add_weighted_adapter(combination_type=...)` call.

#### Scenario: dare_ties is the default
- **WHEN** `TiesDareAdapterMerger()` is constructed without args
- **THEN** `combination_type` is `"dare_ties"`

#### Scenario: Invalid combination type rejected at construction
- **WHEN** `TiesDareAdapterMerger(combination_type="garbage")` is
  constructed
- **THEN** `ValueError` is raised with a message naming the three
  allowed values

### Requirement: Configurable density and per-adapter weights
DARE-based modes SHALL accept a `density` float in `(0, 1]`
(default `0.5`) controlling the survival fraction. All modes SHALL
accept a `weights: list[float]` (default empty = uniform) controlling
per-adapter contribution.

#### Scenario: Density forwarded to peft
- **WHEN** `TiesDareAdapterMerger(combination_type="dare_ties",
  density=0.7).merge(...)` is called and peft is available
- **THEN** the recorded `add_weighted_adapter` call carries
  `density=0.7`

#### Scenario: Uniform weights when omitted
- **WHEN** `weights=[]` (default) and 2 adapter paths are merged
- **THEN** the forwarded weights are `[0.5, 0.5]`

### Requirement: Capability-loss veto rejects degraded merges
The merger SHALL run the configured `CapabilityEval` on the merged
adapter (loaded onto the base model) AND on each parent adapter
individually, compute the parents' mean score, and reject the merge
when `(parent_mean - merged_score) >
capability_loss_threshold` (default `0.05`). Rejection SHALL delete
the on-disk merged adapter and return the input adapter list
unchanged with `metadata.adapter_merge_rejected` containing the
numeric loss.

#### Scenario: Reject on capability drop
- **WHEN** parents score 0.60 and 0.62 (mean 0.61), merged scores
  0.50, threshold 0.05
- **THEN** the merged adapter directory is removed, returned
  adapter list equals `adapters_a + adapters_b` deduplicated, and
  metadata.adapter_merge_rejected ≈ "0.11"

#### Scenario: Accept on small drop
- **WHEN** parents mean 0.61, merged 0.58, threshold 0.05
- **THEN** the merged adapter is kept and returned as a one-item
  list

### Requirement: Merged-adapter output layout is deterministic
Merged adapters SHALL be written to
`<output_dir>/<merge_snapshot_id>/<timestamp>/` where
`merge_snapshot_id` is the `<a>+<b>` id constructed by
`ForkManager.merge`. Two merges of the same parent pair at
different times SHALL not collide.

#### Scenario: Two merges of same parents coexist
- **WHEN** the same parent pair is merged twice with a wait
  between
- **THEN** two timestamped subdirectories exist under the same
  `<merge_snapshot_id>/` parent dir, and both load via
  `peft.PeftModel.from_pretrained`

### Requirement: ForkManager dispatches to TiesDareAdapterMerger via config
`merger_from_name("ties_dare")` SHALL return a configured
`TiesDareAdapterMerger`. When `[lifecycle].adapter_merger =
"ties_dare"` is set in `config/kaine.toml`, `ForkManager` SHALL use
it for every merge operation.

#### Scenario: Config selects the merger
- **WHEN** `[lifecycle].adapter_merger = "ties_dare"` and
  `ForkManager.merge(a_id, b_id)` runs
- **THEN** the adapter step invokes `TiesDareAdapterMerger.merge`
  rather than `FakeAdapterMerger.merge`

### Requirement: ADAPTER_MERGING.md doc ships
The repository SHALL include
`kaine/lifecycle/ADAPTER_MERGING.md` covering: the three
combination modes and when each is appropriate, the
capability-loss veto, the rollback procedure (delete the merged
adapter directory; sources remain untouched), and a note that
TIES/DARE applies only to LoRA adapters from the same base model.

#### Scenario: Document exists
- **WHEN** an operator checks out the change
- **THEN** `kaine/lifecycle/ADAPTER_MERGING.md` is present and
  references peft's `add_weighted_adapter` and the
  capability-loss veto

### Requirement: ForkManager.merge refuses when both parents have trained adapters and no real merger is available

`ForkManager.merge()` SHALL raise `UnmergedAdaptersError` when the
`_adapter_merger.merge()` call returns metadata with `adapter_merge_skipped`
set AND both parent snapshots have non-empty adapter lists, UNLESS
`allow_unmerged_adapters=True` is passed explicitly. This prevents the system
from producing a snapshot that claims to be the result of a merge while its
adapter weights were never combined.

#### Scenario: Merge refused when both parents have adapters and merger is fake

- **WHEN** `ForkManager.merge(a_id, b_id)` is called
- **AND** snapshot `a` has one or more trained adapters
- **AND** snapshot `b` has one or more trained adapters
- **AND** the configured `AdapterMerger` returns `adapter_merge_skipped` in
  its metadata (i.e. no real weight merge was performed)
- **THEN** `UnmergedAdaptersError` is raised with a message naming both
  parent snapshot IDs and the reason
- **AND** no merged snapshot is written to disk

#### Scenario: Merge bypassed with explicit acknowledgement flag

- **WHEN** `ForkManager.merge(a_id, b_id, allow_unmerged_adapters=True)` is
  called with both parents having adapters
- **THEN** the merge proceeds and the resulting snapshot's metadata contains
  `adapter_merge_skipped` recording the reason

#### Scenario: Merge with only one parent having adapters proceeds normally

- **WHEN** exactly one parent has adapters
- **THEN** the merge proceeds without raising (trivial union, no weight
  conflict)

### Requirement: Nexus POST /diagnostics/merges surfaces UnmergedAdaptersError as HTTP 409

The Nexus `POST /diagnostics/merges` handler SHALL catch
`UnmergedAdaptersError` and return HTTP 409 (Conflict) with the error message
as the response body. The request body SHALL accept an `allow_unmerged_adapters`
boolean field (default `false`) that is threaded through to `ForkManager.merge()`.

#### Scenario: Merge API returns 409 when adapters unmerged

- **WHEN** `POST /diagnostics/merges` is called with two snapshots that both
  have trained adapters and no real merger is configured
- **THEN** the response status is 409 with the `UnmergedAdaptersError` message

#### Scenario: Merge API proceeds when allow_unmerged_adapters is true

- **WHEN** `POST /diagnostics/merges` is called with `allow_unmerged_adapters: true`
- **THEN** the merge proceeds and returns 200 with the merged snapshot id

