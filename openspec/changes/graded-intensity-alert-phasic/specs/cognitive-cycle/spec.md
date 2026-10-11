## ADDED Requirements

### Requirement: The access rate's phasic input counts alerts only
The phasic input to the access rate SHALL be computed from the highest intensity among the tick's module reports whose payload has `alert` true; reports without it SHALL NOT count, so with no alert the access rate rests at its resting value.

#### Scenario: A graded report does not raise the rate
- **WHEN** a tick's only module report has intensity 0.6 and no alert flag, at baseline arousal
- **THEN** the phasic input is 0 and the access rate is the resting rate

#### Scenario: An alert raises the rate
- **WHEN** a tick's module reports include one with intensity 0.8 and `alert` true
- **THEN** the phasic input is greater than 0
