## ADDED Requirements

### Requirement: The step record carries the step's welfare exposure
After each step the study runner SHALL copy the step's `state/welfare/exposure.json` into the step record as `welfare_exposure` when its `run_id` equals the step's run id and its `boot_started_at` is after the step's start, and the analysis SHALL print a per-step exposure table.

#### Scenario: A completed step
- **WHEN** step 2 of the development run completes with a valid record
- **THEN** its step record carries `welfare_exposure` and the analysis table has a row for it

### Requirement: The run holds for review after a step with an indicator crossing
The runner SHALL NOT start the next step after a step whose exposure record is missing, unreadable, bound to another run or boot, incomplete in coverage, or shows any indicator crossing, until the operator answers with `ack-welfare` naming the step and the decision `continue` or `stop`. The answer SHALL be recorded in the study record and SHALL NOT edit any entity's state. `status` SHALL show a pending hold.

#### Scenario: A rest during a step
- **WHEN** a step completes after one indicator rest and no freeze
- **THEN** the next step does not start and `status` names the hold and the command to answer it

#### Scenario: A missing record
- **WHEN** a step completes without an exposure record
- **THEN** the run holds as for a crossing

#### Scenario: A record from another run
- **WHEN** the step directory holds an exposure record whose `run_id` is not the step's
- **THEN** the record is not copied and the run holds

#### Scenario: Incomplete coverage
- **WHEN** the record shows `producer_restarts` 1
- **THEN** the run holds for review

#### Scenario: The operator continues
- **WHEN** the operator answers `ack-welfare` with `continue`
- **THEN** the acknowledgement is recorded and the next step starts on the next `run`
