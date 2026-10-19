## ADDED Requirements

### Requirement: The footprint measurement uses a reported result even when the child does not exit
A footprint measurement SHALL use the result a child reports even when the child then fails to exit, stopping the child and noting that it was stopped after reporting.

#### Scenario: A child that reports and keeps running
- **WHEN** the measured callable returns its result and leaves a non-daemon thread running
- **THEN** the measurement succeeds and its note says the child was stopped after reporting
