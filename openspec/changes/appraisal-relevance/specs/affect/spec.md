## MODIFIED Requirements

### Requirement: Goal significance is scored against the entity's dominant drive
The affect module's goal-significance appraisal check SHALL score the selected events against the entity's dominant drive (the highest-valued affect drive, ties broken by name), using the drive-to-source table built from each registered module's `relieves_drives` declaration and injected by the boot wiring and re-injected when the affect module is restarted. With dominant drive value `v > 0` and `f` the salience-weighted share of selected events whose source relieves that drive (`0` for an empty coalition or a zero total), the drive score SHALL be `v × f`. With no drive above zero, the drive score SHALL be `0.0`. When the goal ledger holds active goals, the check SHALL return the larger of the drive score and the ledger `relevance` (the ledger relevance alone when no table was injected); otherwise it SHALL return the drive score, or `0.0` when no table was injected. The score SHALL lie in `[0, 1]`: content that serves neither the drive nor a goal is irrelevant, not obstructive. No constant offset SHALL be applied.

#### Scenario: Content serving a pressing need is goal-conducive
- **WHEN** the social drive is the dominant drive at 0.8 and every selected event comes from a source that relieves the social drive
- **THEN** goal significance is 0.8

#### Scenario: Content ignoring a pressing need is irrelevant
- **WHEN** the social drive is the dominant drive at 0.8 and no selected event comes from a source that relieves it
- **THEN** goal significance is 0.0

#### Scenario: An empty coalition is irrelevant
- **WHEN** the curiosity drive is the dominant drive at 0.3 and the coalition is empty
- **THEN** goal significance is 0.0

#### Scenario: An idle coalition does not classify as anger
- **WHEN** the dominant drive is unmet, no selected event relieves it, and affect is at baseline
- **THEN** the categorical emotion is not `anger`

#### Scenario: No pressing need
- **WHEN** every drive is at 0.0 and no goals are active
- **THEN** goal significance is 0.0
