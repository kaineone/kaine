## MODIFIED Requirements

### Requirement: Loss of supervision escalates during an unattended run
When the cycle runs in unattended or research mode and the supervisor's supervision task exits for any reason other than shutdown, the cycle SHALL run the supervisor's escalation (final snapshot, shutdown of every module, and `escalation.json`) and SHALL send a caretaker notice. In operator-present mode this requirement SHALL NOT apply.

#### Scenario: Supervisor task crashes unattended
- **WHEN** the supervisor's supervision task raises during an unattended run
- **THEN** the cycle escalates, the entity is preserved and shut down, and a caretaker notice is sent

#### Scenario: Supervisor task crashes in a research run
- **WHEN** the supervisor's supervision task raises during a research run
- **THEN** the cycle escalates, the entity is preserved and shut down, and a caretaker notice is sent

#### Scenario: Operator-present boot unaffected
- **WHEN** the supervisor's supervision task exits during an operator-present boot
- **THEN** the escalation is not applied and behavior is unchanged
