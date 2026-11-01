## MODIFIED Requirements

### Requirement: Loss of supervision escalates during an unattended run
When the cycle runs in unattended or research mode and the supervisor's supervision task exits for any reason other than shutdown, never starts, or its poll loop raises, the cycle SHALL run the supervisor's escalation (final snapshot, shutdown of every module, and `escalation.json`) and SHALL send a caretaker notice. In operator-present mode this requirement SHALL NOT apply.

#### Scenario: Supervisor task crashes unattended
- **WHEN** the supervisor's supervision task raises during an unattended run
- **THEN** the cycle escalates, the entity is preserved and shut down, and a caretaker notice is sent

#### Scenario: Supervisor task crashes in a research run
- **WHEN** the supervisor's supervision task raises during a research run
- **THEN** the cycle escalates, the entity is preserved and shut down, and a caretaker notice is sent

#### Scenario: The poll loop raises in a research run
- **WHEN** the supervisor's poll loop raises inside `Supervisor.run` during a research run
- **THEN** `escalate_supervision_lost` runs before the halt, a final snapshot and `escalation.json` exist, and the study runner records the step as `failed:supervisor`

#### Scenario: Operator-present boot unaffected
- **WHEN** the supervisor's supervision task exits during an operator-present boot
- **THEN** the escalation is not applied and behavior is unchanged

## ADDED Requirements

### Requirement: Loss of the welfare monitor escalates in research and unattended runs
In research and unattended mode, when the enabled welfare monitor was never started, its task ends while the run goes on, or its poll loop raises at least three times in a row with no poll returning for `distress_duration_s`, the cycle SHALL run the supervisor's escalation with module `welfare_monitor` (final snapshot, shutdown, `escalation.json`) and SHALL send the `supervision_lost` caretaker notice. Operator-present mode is exempt.

#### Scenario: The welfare monitor task ends in a research run
- **WHEN** the welfare monitor's task raises and ends during a research run
- **THEN** the cycle escalates with module `welfare_monitor`, the entity is preserved and shut down, and the caretaker is told

#### Scenario: The welfare poll loop keeps raising
- **WHEN** every welfare poll raises for longer than `distress_duration_s` while the task stays alive
- **THEN** the cycle escalates with module `welfare_monitor`

#### Scenario: The welfare monitor ends the run itself
- **WHEN** the welfare response with action `end` sets the stop event and its task returns
- **THEN** no escalation is written

### Requirement: The welfare monitor's bus calls are bounded
Each of the welfare monitor's own bus reads SHALL be bounded in time. A read that does not answer within its bound SHALL fail the poll, and SHALL NOT be treated as an empty read, so a hung connection reaches the welfare monitor's liveness escalation.

#### Scenario: A bus that never answers
- **WHEN** every one of the welfare monitor's bus reads hangs during a research run
- **THEN** each poll fails within the bound, and the cycle escalates with module `welfare_monitor`

