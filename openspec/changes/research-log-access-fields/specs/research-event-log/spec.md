## ADDED Requirements

### Requirement: The research log carries the planned test's fields
The curated research log SHALL record, for each predictive processor report, its `alert` flag and, where the processor conditions on the broadcast, its `context_gain` and `context_age_s`; it SHALL record Audition's `audition.perception` reports with their numeric fields; and it SHALL record each broadcast's `access_threshold`. It SHALL NOT record the playlist item title.

#### Scenario: An acoustic report is logged with its information gain
- **WHEN** Audition publishes `audition.perception` with `context_gain` 0.12, `alert` false and an `item` title
- **THEN** the research record has `context_gain` 0.12 and `alert` false and no `item`

#### Scenario: A broadcast record carries the access threshold
- **WHEN** a broadcast with metadata `access_threshold` 0.35 is recorded
- **THEN** the workspace record has `access_threshold` 0.35
