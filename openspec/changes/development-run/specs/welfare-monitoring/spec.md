## ADDED Requirements

### Requirement: A development-run pass ends with its own exposure record
In a development-run session the cycle SHALL write, at every pass end and before the pass-end preservation is requested, a content-free exposure record for that pass at `state/welfare/exposure/pass-<n>.json`, with the same fields as the run-level exposure record computed over the pass's awake time. It SHALL keep writing the run-level record at stop. A pass whose record cannot be written SHALL be logged at error level, and the runner SHALL treat the missing record as a crossing.

#### Scenario: Two passes in one session
- **WHEN** a session plays two passes and stops
- **THEN** `pass-1.json` and `pass-2.json` exist, each over its own pass, and the run-level record covers the session

#### Scenario: A write failure
- **WHEN** the pass record cannot be written
- **THEN** an error-level log line names the pass and the runner holds as for a crossing
