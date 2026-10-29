## ADDED Requirements

### Requirement: A spent stimulus requests a developmental rest
The affect module SHALL record the latest entity time at which, on an update, the learning progress above the floor (`lp+`) or the alert excess was above zero. When a boredom goal is abandoned as stalled, the module SHALL publish `affect.rest_request` on `affect.out` with `reason` `"stimulus_spent"`, `drive` `"boredom"` and `stall_s` the stall length, if and only if the development probe reports the entity as developing and that latest time is before the start of the stall or does not exist (paper section 3.5). A probe that raises SHALL count as developing; with no probe no request SHALL be published. The time since the latest engagement SHALL persist in the snapshot as a duration, and a snapshot without it SHALL count as engaged at the restore.

#### Scenario: A spent stimulus
- **WHEN** a developing entity's boredom stays at or above its threshold for the stall horizon with `lp+` and the alert excess zero throughout
- **THEN** the boredom goal is abandoned as stalled and one `affect.rest_request` with reason `stimulus_spent` is published

#### Scenario: Progress during the stall
- **WHEN** `lp+` was above zero at any update during the stall
- **THEN** the goal is abandoned as stalled and no rest request is published

#### Scenario: After maturation
- **WHEN** the development probe reports the entity as matured
- **THEN** no rest request is published
