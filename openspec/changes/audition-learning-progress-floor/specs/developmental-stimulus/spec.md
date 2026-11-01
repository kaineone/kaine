## ADDED Requirements

### Requirement: The hearing-stage owner uses audition's floor
The hearing-stage owner's `lp_0` SHALL be `[affect].audition_learning_progress_floor` when it is set, and `[affect].learning_progress_floor` otherwise. The developmental stimulus version SHALL carry it.

#### Scenario: The configured audition floor reaches the owner
- **WHEN** boot installs the stage owner with `audition_learning_progress_floor = 0.12`
- **THEN** a full-span reading of 0.15 counts as unsaturated
