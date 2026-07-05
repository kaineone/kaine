## ADDED Requirements

### Requirement: ForkSnapshot captures every registered module's state
`ForkManager.snapshot(registry, label)` SHALL produce a
`ForkSnapshot` containing one entry per registered module under
`modules[<name>]`, each carrying that module's `serialize()` output.
The snapshot SHALL also carry `id`, `parent_id` (None for root
snapshots), `label`, `timestamp`, `adapters` (list of adapter paths),
and `metadata`. The snapshot SHALL be persisted atomically to
`state/forks/<id>/snapshot.json` and SHALL be loadable from that
path.

#### Scenario: Roundtrip preserves module states
- **WHEN** a registry containing two modules with non-trivial state
  is snapshotted and then loaded into fresh modules
- **THEN** each fresh module's serialize() returns the same shape
  as the originals'

#### Scenario: Snapshot id is unique
- **WHEN** two snapshots are created in succession
- **THEN** they have distinct ids and the second carries the first's
  id in its parent_id field when fork() was used

### Requirement: Fork carries forward state minus shed modules
`ForkManager.fork(parent_id, *, label, shed)` SHALL produce a child
snapshot whose `modules` dict excludes every name listed in `shed`
and whose `parent_id` is the parent's id. The child's other module
states SHALL be deep-copies of the parent's, not references.

#### Scenario: Shed module excluded from child
- **WHEN** parent has modules `{"soma", "chronos", "topos"}` and
  `fork(shed=["topos"])` is called
- **THEN** the child snapshot's `modules` has keys
  `{"soma", "chronos"}` only

### Requirement: Merge composes per-module strategies
ForkManager.merge SHALL invoke the registered `MergeStrategy` for each
module name present in either parent. For names missing from one
parent, the strategy SHALL be invoked with `state_b=None` (or
`state_a=None`). The merged result SHALL be written as a new
snapshot whose `parent_id` is `<a>+<b>` (formatted as the two ids
joined with `+`).

#### Scenario: Union-by-default for unknown modules
- **WHEN** the default `UnionMergeStrategy` is invoked on
  `{"a": 1, "b": 2}` and `{"b": 3, "c": 4}`
- **THEN** the merged state is `{"a": 1, "b": 3, "c": 4}` (b's
  later value wins by default; documented as last-write-wins)

#### Scenario: One-parent-missing handled gracefully
- **WHEN** a module is present only in `snapshot_a`
- **THEN** the strategy is invoked with `state_b=None` and the
  child snapshot carries `state_a`'s value under that name

### Requirement: Mnemos merge unions memories with source tags
The `MnemosMergeStrategy` SHALL union the `short_term_size` from
both parents (sum), and SHALL append a `source` tag (e.g.
`fork-a`, `fork-b`) to every recovered memory entry's metadata when
the merged snapshot is loaded back into a Mnemos instance. The
strategy SHALL preserve the `collection_prefix` and `embedder_model_id`
from the parents (when they match) or annotate `metadata` with
`prefix_mismatch=True` when they don't.

#### Scenario: Same prefix preserved
- **WHEN** both parents have `collection_prefix == "mnemos_"`
- **THEN** the merged state has `collection_prefix == "mnemos_"` and
  `metadata.prefix_mismatch` is unset

### Requirement: Nous merge sketches additive belief revision
The `NousMergeStrategy` SHALL combine both parents' `restart_count`
(sum) and SHALL set a `pending_revision` flag in the merged state's
metadata so the merged Nous instance knows to re-derive beliefs
from union of inputs on its next inference cycle. v1 SHALL NOT
attempt to literally merge ONA belief tables — the real revision
happens inside ONA at next inference.

#### Scenario: Restart count summed and pending flagged
- **WHEN** parent_a has `restart_count=2` and parent_b has
  `restart_count=3`
- **THEN** the merged state has `restart_count == 5` and
  `pending_revision == True`

### Requirement: Eidolon merge sums drift count and unions values
The `EidolonMergeStrategy` SHALL union `values` and `behavioral_norms`
(deduplicated), sum `internal_speech_count`, and concatenate
`identity_history` with each entry source-tagged. `personality_baseline`
SHALL be averaged when both parents have it.

#### Scenario: Values deduplicated, history concatenated
- **WHEN** parent_a.values=["honesty", "curiosity"] and
  parent_b.values=["curiosity", "patience"]
- **THEN** merged.values is `["honesty", "curiosity", "patience"]`
  (set semantics, order from a-then-b)

### Requirement: AdapterMerger is a protocol with a Fake default
Adapter merging (TIES/DARE) SHALL be invoked via an `AdapterMerger`
protocol. The default `FakeAdapterMerger` SHALL pass adapter paths
through unchanged and annotate `metadata.adapter_merge_skipped =
"no merger configured"`. A real TIES/DARE implementation lands in a
follow-up change gated by operator opt-in.

#### Scenario: No adapter merge in v1
- **WHEN** two parents each have an adapter path and merge is called
  with the default merger
- **THEN** the merged snapshot's `adapters` is a list of both
  paths and its `metadata.adapter_merge_skipped` is set

### Requirement: Default config and disabled-by-default lifecycle
The repository SHALL ship a `[lifecycle]` block in `config/kaine.toml`
with default values for `snapshots_path` (default
`state/forks`), `max_snapshots_retained` (default 64), and
`adapter_merger` (default `fake`). No first-boot integration is
shipped — fork/merge is operator-initiated.

#### Scenario: kaine.toml carries defaults
- **WHEN** an operator inspects `config/kaine.toml`
- **THEN** they find a `[lifecycle]` section with the documented
  keys
