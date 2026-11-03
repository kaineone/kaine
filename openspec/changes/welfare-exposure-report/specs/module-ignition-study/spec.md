## ADDED Requirements

### Requirement: The step record carries the step's welfare exposure
After each step the study runner SHALL copy the step's `state/welfare/exposure.json` into the step record as `welfare_exposure` when its `run_id` equals the step's run id and its `boot_started_at` is after the step's start, and the analysis SHALL print a per-step exposure table.

#### Scenario: A completed step
- **WHEN** step 2 of the development run completes with a valid record
- **THEN** its step record carries `welfare_exposure` and the analysis table has a row for it

### Requirement: The run holds for review after a step with an indicator crossing
The runner SHALL NOT start the next step after a step whose exposure record is missing, unreadable, bound to another run or boot, incomplete in coverage, shows any indicator crossing, or shows any protective response or a response count that cannot be read, until the operator answers with `ack-welfare` naming the step and the decision `continue` or `stop`. The answer SHALL be recorded in the study record and SHALL NOT edit any entity's state. `status` SHALL show a pending hold.

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

#### Scenario: A protective response without a crossing
- **WHEN** a step's boot ends with `action = "end"` after an `indicators_unavailable` response, with no rest and no freeze
- **THEN** the run holds with reason `protective_response`

### Requirement: A failed step whose boot needs review is not retried unanswered
While a failed step's `welfare_hold` names `indicator_crossing` or `protective_response` and has no answer, `--retry-failed` SHALL refuse without booting the entity. `ack-welfare` SHALL answer a failed step's hold; after `stop` the step SHALL NOT be retried. `status` and the halt message SHALL show a failed step's unanswered hold. A hold with only other reasons SHALL NOT block a retry.

#### Scenario: A retry after a crossing
- **WHEN** a step fails after its boot requested an indicator rest and the operator runs `--retry-failed`
- **THEN** the runner refuses with exit code 4, names the hold and boots nothing

#### Scenario: The operator answers the failed step
- **WHEN** the operator answers the failed step's hold with `continue`
- **THEN** the next `--retry-failed` boots the step again

#### Scenario: A crash before the record was written
- **WHEN** a step fails with its exposure record missing
- **THEN** `status` shows the hold and `--retry-failed` boots the step again

### Requirement: A critical step's exposure is read before the entity boots again
A step recorded `failed:critical` while its cycle still ran SHALL have its exposure record read, once no cycle of the study runs, before `--retry-failed` boots the step again; every hold reason on a critical step, a missing record included, SHALL block the retry until `ack-welfare` answers it. Before every boot the runner SHALL copy an existing exposure record aside, and SHALL refuse the boot when the copy cannot be made.

#### Scenario: A boot that crossed, then failed critical
- **WHEN** a step's cycle requested an indicator rest, the step was recorded `failed:critical`, and the cycle wrote its record when it exited
- **THEN** `--retry-failed` reads the record, holds with `indicator_crossing` and boots nothing until the hold is answered

#### Scenario: A critical cycle killed before it wrote
- **WHEN** the critical step's cycle was killed and left no exposure record
- **THEN** `--retry-failed` holds with `missing`

#### Scenario: The cycle still runs
- **WHEN** the critical step's cycle is still running
- **THEN** `--retry-failed` refuses and the record is not read
