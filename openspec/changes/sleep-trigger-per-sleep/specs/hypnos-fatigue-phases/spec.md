## ADDED Requirements

### Requirement: Each sleep records its own trigger
The sleep module SHALL record, for every sleep, the trigger that started that sleep, and SHALL NOT carry a trigger over from an earlier sleep. The trigger SHALL be `fatigue` for an `interoception.fatigue` crossing, `maintenance_request` for an `interoception.regulation` maintenance request, `affect_regulation` for an `affect.regulation` maintenance request, `developmental_rest` for an `affect.rest_request` on a spent stimulus, `requested` for an accepted rest request, `backstop` for the maintenance poll, and null for a direct `enter_sleep()` call without one. `sleep.sleep.started`, `sleep.sleep.completed` and an aborted `sleep.sleep.completed` SHALL carry it as `trigger`, and the summary's `fatigue_triggered` SHALL be true only when that sleep's trigger is `fatigue`. A trigger that loses the start race SHALL leave the running sleep's trigger unchanged.

#### Scenario: A backstop sleep after a fatigue sleep
- **WHEN** a fatigue crossing starts one sleep and the maintenance poll starts the next
- **THEN** the first summary carries `trigger: "fatigue"` and `fatigue_triggered: true`
- **AND** the second carries `trigger: "backstop"` and `fatigue_triggered: false`

#### Scenario: Maintenance requests are not fatigue
- **WHEN** an `interoception.regulation` or `affect.regulation` maintenance request starts a sleep
- **THEN** its summary carries `trigger: "maintenance_request"` or `trigger: "affect_regulation"` and `fatigue_triggered: false`

#### Scenario: A losing trigger
- **WHEN** a second trigger arrives while a sleep is starting or running
- **THEN** no second sleep starts and the running sleep's events keep its own trigger

#### Scenario: The research log keeps the trigger
- **WHEN** the research event observer records `sleep.sleep.started` or `sleep.sleep.completed`
- **THEN** the record keeps `trigger`
