## ADDED Requirements

### Requirement: The sleep panel names every recorded trigger
The dashboard's sleep and rest panel SHALL show a label for each trigger the sleep module records: `fatigue`, `maintenance_request`, `affect_regulation`, `state_cycle`, `requested` and `backstop`, and SHALL keep its labels for `developmental_rest` and `fatigue_or_backstop`. It SHALL show `not known` only for a sleep with no trigger.

#### Scenario: A fatigue sleep
- **WHEN** the last sleep's trigger is `fatigue`
- **THEN** the panel shows "fatigue", not "not known"

#### Scenario: A sleep for emotion regulation
- **WHEN** the last sleep's trigger is `affect_regulation`
- **THEN** the panel shows "emotion regulation"
