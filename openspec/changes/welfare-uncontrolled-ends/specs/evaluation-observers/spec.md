## ADDED Requirements

### Requirement: Every abandoned goal end counts as uncontrolled in the affect welfare record
The welfare observer's `affect_welfare` record SHALL count, per drive, a goal end as uncontrolled ("other") when its `affect.goal` action is `abandoned` and its reason is `without_response`, `stalled` or `cap`, and as own when its action is `completed` and its reason is `own_response` (paper 6.2, A.4). A `cleared` end with reason `sleep_reset` SHALL count as neither. Any other action or reason SHALL count as neither, so that an unknown reason is never credited.

#### Scenario: A stalled goal is an uncontrolled end
- **WHEN** a curiosity goal ends `abandoned` with reason `stalled` three times and `completed` with reason `own_response` once
- **THEN** `curiosity_uncontrolled_share` is 0.75

#### Scenario: A cap-dropped goal is an uncontrolled end
- **WHEN** the only boredom goal end is `abandoned` with reason `cap`
- **THEN** `boredom_uncontrolled_share` is 1.0

#### Scenario: A sleep reset counts as neither
- **WHEN** the only social-drive goal end is `cleared` with reason `sleep_reset`
- **THEN** `social_drive_uncontrolled_share` is null

#### Scenario: An unknown reason counts as neither
- **WHEN** the only restlessness goal ends are `abandoned` with an unrecognised reason and `completed` with a reason other than `own_response`
- **THEN** `restlessness_uncontrolled_share` is null and `restlessness_uncontrolled_per_awake_hour` is 0
