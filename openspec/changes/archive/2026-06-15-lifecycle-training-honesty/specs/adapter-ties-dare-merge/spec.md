## ADDED Requirements

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
