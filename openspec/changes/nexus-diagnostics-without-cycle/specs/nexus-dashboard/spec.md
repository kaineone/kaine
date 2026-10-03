## ADDED Requirements

### Requirement: Diagnostics renders without a running cycle
The diagnostics page SHALL render successfully when no cycle is running, whether or not operator controls are enabled, treating every cycle metric the stopped-cycle snapshot omits as absent.

#### Scenario: Controls on, cycle stopped
- **WHEN** controls are enabled and the metrics snapshot holds only `cycle_status` and a hint
- **THEN** `GET /diagnostics/` answers 200 and shows the rate form without an effective-rate line
