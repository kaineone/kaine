## ADDED Requirements

### Requirement: A boredom stall starts no rest
When a boredom goal is abandoned as stalled, the affect module SHALL publish the goal's abandonment as before and SHALL NOT publish `affect.rest_request`. An affect snapshot that carries the former engagement field SHALL restore without error and the field SHALL be ignored.

#### Scenario: A stall in the developmental phase
- **WHEN** a boredom goal stalls with no learning progress throughout the stall
- **THEN** the goal is abandoned with reason `stalled` and no `affect.rest_request` is published
