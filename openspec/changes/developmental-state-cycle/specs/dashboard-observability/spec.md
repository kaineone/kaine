## ADDED Requirements

### Requirement: The sleep panel names the state-cycle rest
The dashboard's sleep panel SHALL label a sleep with trigger `state_cycle` as a state-cycle rest and SHALL show its rest length.

#### Scenario: A state-cycle rest
- **WHEN** the latest sleep has trigger `state_cycle` and `rest_seconds` 1410
- **THEN** the sleep panel shows a state-cycle rest of 1410 s

### Requirement: Earlier records stay readable and the rest-request line is gone
The sleep panel SHALL label a sleep with trigger `developmental_rest`, recorded under the earlier rule, as a developmental rest of the earlier rule, and SHALL show no rest-request line, because the affect module no longer publishes `affect.rest_request`.

#### Scenario: An earlier developmental rest
- **WHEN** the latest sleep has trigger `developmental_rest`
- **THEN** the sleep panel labels it as a developmental rest (earlier rule)
