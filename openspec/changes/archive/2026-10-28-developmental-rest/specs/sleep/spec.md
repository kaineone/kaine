## ADDED Requirements

### Requirement: A developmental rest lasts developmental_rest_s
On an `affect.rest_request` with reason `stimulus_spent`, the sleep module SHALL start a sleep with trigger `developmental_rest` under the same guards as the other event-driven triggers. That sleep SHALL run its phases and then stay asleep until `[sleep].developmental_rest_s` (default 1,260 s, Table A1 Delta_rest) of entity time has passed since it began, and SHALL then end with the affective reset. A cancel during the hold SHALL still run the affective reset. Its `sleep.sleep.started` event SHALL carry `trigger` `developmental_rest`, and its `sleep.sleep.completed` summary SHALL carry `trigger` and `rest_seconds`. Every other sleep SHALL end with its phases as before, and its events SHALL be unchanged. `developmental_rest_s` SHALL be a finite number greater than 0.

#### Scenario: The rest holds
- **WHEN** a developmental rest begins and its phases finish after 10 s
- **THEN** the sleep ends with the affective reset 1,260 s of entity time after it began

#### Scenario: An ordinary sleep
- **WHEN** a fatigue-triggered sleep runs
- **THEN** it ends when its phases finish and its summary has no `rest_seconds`
