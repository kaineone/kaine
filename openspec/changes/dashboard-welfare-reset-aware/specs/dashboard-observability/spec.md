## ADDED Requirements

### Requirement: Dashboard welfare counts honour restart resets
The dashboard SHALL compute welfare counts with the reset-aware reader, so a count after a restart reset is not raised by records from before it. The evaluation tab SHALL show only data that a running component produces.

#### Scenario: Dashboard welfare counts honour restart resets
- **WHEN** the welfare JSONL holds a count of 5, then a restart reset, then a count of 0
- **THEN** the dashboard shows 0
