## ADDED Requirements

### Requirement: Dashboard welfare counts honour restart resets
The dashboard SHALL compute welfare counts with the reset-aware reader, so a count after a restart reset is not raised by records from before it. The evaluation tab SHALL read only the rollups the cycle writes, and SHALL NOT report counters from a sidecar registry the dashboard process never starts.

#### Scenario: Dashboard welfare counts honour restart resets
- **WHEN** the welfare JSONL holds a count of 5, then a restart reset, then a count of 0
- **THEN** the dashboard shows 0

#### Scenario: No registry stands in for the cycle
- **WHEN** the dashboard builds the evaluation tab
- **THEN** it builds no sidecar registry and no panel reports a source of live
