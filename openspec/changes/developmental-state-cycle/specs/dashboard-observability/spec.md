## ADDED Requirements

### Requirement: The sleep panel names the state-cycle rest
The dashboard's sleep panel SHALL label a sleep with trigger `state_cycle` as a state-cycle rest and SHALL show its rest length.

#### Scenario: A state-cycle rest
- **WHEN** the latest sleep has trigger `state_cycle` and `rest_seconds` 1410
- **THEN** the sleep panel shows a state-cycle rest of 1410 s
