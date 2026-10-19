## ADDED Requirements

### Requirement: Interest goal factor
With `[workspace].salience_goal_factor = "interest"`, the goal factor of a candidate from source `m` SHALL be `1 + gamma_I * D_I * lp+_m`. In it:
- `gamma_I` is `[workspace].interest_gain` (default 0.5, at least 0).
- `D_I` is the last-known curiosity value.
- `lp+_m` is `max(0, lp_m - lp_0) / (1 - lp_0)`, with `lp_m` the last-known `<m>_learning_progress` of `affect.state` and `lp_0` `[affect].learning_progress_floor`.
- `lp+_m` is 0 when the source has no finite learning progress.

The factor SHALL be exactly 1 when curiosity is 0 or unknown, and for any source without learning progress.

#### Scenario: No interest leaves selection unbiased
- **WHEN** curiosity is 0 and vision's learning progress is 0.9
- **THEN** a vision report's goal factor is exactly 1

#### Scenario: A non-perceptual source is never biased
- **WHEN** curiosity is 0.96 and vision's learning progress is 0.9
- **THEN** an `affect.drive` event's and a `sequence.report`'s goal factors are exactly 1

#### Scenario: The progressing source is raised
- **WHEN** curiosity is 0.96, vision's learning progress is 0.9, the floor is 0.05 and `gamma_I` is 0.5
- **THEN** a vision report's goal factor is `1 + 0.5 * 0.96 * (0.85 / 0.95)`

### Requirement: Only the priority is clipped
The salience score SHALL clip the priority `intensity * novelty * goal` to `[0, 1]` and SHALL NOT clip the goal factor above 1; a negative or non-finite goal factor SHALL count as 0. With the static or drive-relevance goal factor every score SHALL be unchanged.

#### Scenario: A raised factor saturates the priority
- **WHEN** an event of intensity 0.7 and novelty 1 has goal factor 1.5
- **THEN** its priority is 1

### Requirement: The interest factor keeps the affect snapshot live
When the interest goal factor is selected, the cycle SHALL refresh the affect state provider each tick. The provider SHALL fold each finite `<source>_learning_progress` term of the latest `affect.state`.

#### Scenario: Learning progress reaches the scorer
- **WHEN** an `affect.state` with `vision_learning_progress` 0.6 and curiosity 0.5 is observed
- **THEN** the interest scorer reads 0.6 for vision and 0.5 for curiosity
