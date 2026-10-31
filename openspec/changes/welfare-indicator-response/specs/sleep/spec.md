## ADDED Requirements

### Requirement: A welfare rest request starts a rest after maturation
The sleep module SHALL read `welfare.rest_request` from the welfare monitor's stream. After maturation, or with staging disabled, it SHALL start a sleep with trigger `welfare_rest` through the maintenance path, regardless of the fatigue-maintenance toggle and of the requested-rest minimum interval, ending with its phases and the affective reset. Its `sleep.sleep.started` and `sleep.sleep.completed` events SHALL carry `trigger` `welfare_rest`.

#### Scenario: After maturation with fatigue maintenance off
- **WHEN** a matured entity's sleep module, with fatigue-triggered maintenance off, reads a welfare rest request while awake
- **THEN** a sleep with trigger `welfare_rest` starts and ends with the affective reset

### Requirement: A welfare rest request brings the state cycle's rest forward
In the developmental phase the sleep module SHALL answer a welfare rest request by starting a sleep with trigger `welfare_rest` that holds until `developmental_rest_s` of entity time has passed since it began, as a state-cycle rest does. The state cycle's awake stretch SHALL restart when it completes.

#### Scenario: The developmental phase
- **WHEN** a developing entity's sleep module reads a welfare rest request 1000 s into an awake stretch
- **THEN** a rest of 1410 s starts now, and the next state-cycle rest comes a full awake stretch after it ends

### Requirement: A welfare rest request during a sleep is answered busy
When a sleep is already running, the sleep module SHALL answer a welfare rest request with a `sleep.rest_request` that has `accepted` false, `reason` `busy` and `origin` `welfare`, and SHALL start no second sleep.

#### Scenario: A request during a sleep
- **WHEN** a welfare rest request arrives while a sleep runs
- **THEN** the module answers `busy` with origin `welfare` and starts no second sleep
