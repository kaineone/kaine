## ADDED Requirements

### Requirement: The step record carries the viewing's welfare exposure
After each step the study runner SHALL copy the step's `state/welfare/exposure.json` into the step record as `welfare_exposure`, and the analysis SHALL print a per-viewing exposure table beside the ignition measures.

#### Scenario: A completed viewing
- **WHEN** branch 2 completes
- **THEN** its step record carries `welfare_exposure` and the analysis table has a row for it

### Requirement: The study holds for review after a viewing with an indicator crossing
The runner SHALL NOT start the next step after a step whose exposure record is missing or unreadable, or shows any indicator crossing, until the operator answers with `ack-welfare` naming the step and the decision `continue` or `stop-line`. The answer SHALL be recorded in the study record and SHALL NOT edit any entity's state. `status` SHALL show a pending hold.

#### Scenario: A rest during a viewing
- **WHEN** a viewing completes after one indicator rest and no freeze
- **THEN** the next step does not start and `status` names the hold and the command to answer it

#### Scenario: A missing record
- **WHEN** a step completes without an exposure record
- **THEN** the study holds as for a crossing

#### Scenario: The operator continues
- **WHEN** the operator answers `ack-welfare` with `continue`
- **THEN** the acknowledgement is recorded and the next step starts on the next `run`
