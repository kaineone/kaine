## MODIFIED Requirements

### Requirement: thymos.emotion event discloses goal_significance method

The `thymos.emotion` event payload SHALL carry `goal_significance_method`, naming how the published `goal_significance` score was computed: `"drive_relevance_v1"` when it was scored against the entity's dominant drive, `"drive_relevance_v1+token_overlap_v1"` when active ledger goals also contributed, `"token_overlap_v1"` when no drive-to-source table was injected and active ledger goals were scored, and `"unavailable"` when neither source exists, in which case the score SHALL be `0.0`.

#### Scenario: goal_significance is a proxy

- **WHEN** a `thymos.emotion` event is published by a Thymos assembled into the cycle with no active goals
- **THEN** the payload carries `"goal_significance_method": "drive_relevance_v1"`

#### Scenario: No table

- **WHEN** a `thymos.emotion` event is published by a Thymos that was given no drive-to-source table and holds no active goals
- **THEN** the payload carries `"goal_significance_method": "unavailable"` and `goal_significance` is `0.0`

## ADDED Requirements

### Requirement: Goal significance is scored against the entity's dominant drive
Thymos's goal-significance appraisal check SHALL score the selected events against the entity's dominant drive (the highest-valued Thymos drive, ties broken by name), using the drive-to-source table built from each registered module's `relieves_drives` declaration and injected by the boot wiring and re-injected when Thymos is restarted. With dominant drive value `v > 0` and `f` the salience-weighted share of selected events whose source relieves that drive, the drive score SHALL be `v × (2f − 1)`. With no drive above zero, the drive score SHALL be `0.0`. When the goal ledger holds active goals, the check SHALL return the larger of the drive score and `relevance × 2 − 1` (the ledger score alone when no table was injected); otherwise it SHALL return the drive score, or `0.0` when no table was injected. No constant offset SHALL be applied.

#### Scenario: Content serving a pressing need is goal-conducive
- **WHEN** the social drive is the dominant drive at 0.8 and every selected event comes from a source that relieves the social drive
- **THEN** goal significance is 0.8

#### Scenario: Content ignoring a pressing need is obstructive
- **WHEN** the social drive is the dominant drive at 0.8 and no selected event comes from a source that relieves it
- **THEN** goal significance is -0.8

#### Scenario: No pressing need
- **WHEN** every drive is at 0.0 and no goals are active
- **THEN** goal significance is 0.0
