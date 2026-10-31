## ADDED Requirements

### Requirement: A failed stop hook falls back to the welfare pause
When the welfare response's action is `end` and the stop hook is not wired or raises, the protective welfare monitor SHALL place the welfare freeze instead and record the action as `pause_fallback`. When the hook raised, the record SHALL carry the hook's error, with paths scrubbed, in `end_error`, and the failure SHALL be logged at error level. The record SHALL NOT claim an `end` that was not enacted.

#### Scenario: The stop hook raises
- **WHEN** the response's action is `end` and the stop hook raises
- **THEN** the entity is preserved and the welfare freeze is placed
- **AND** the `welfare.protective_action` record has action `pause_fallback` and the hook's error in `end_error`

#### Scenario: No stop hook is wired
- **WHEN** the response's action is `end` and no stop hook is wired
- **THEN** the welfare freeze is placed and the record has action `pause_fallback`

### Requirement: A welfare freeze that cannot be written is recorded and notified
When writing the welfare freeze raises, for a `pause` or a `pause_fallback`, the protective welfare monitor SHALL NOT let the error end the response. It SHALL log the error, record the response with the transition `protective_action_freeze_failed` and the error, with paths scrubbed, in `freeze_error`, and notify the caretaker as for a response whose freeze was written. A record whose freeze was written SHALL carry `freeze_error` as null.

#### Scenario: The freeze cannot be written
- **WHEN** the response preserves the entity and writing the welfare freeze raises an `OSError`
- **THEN** the response is recorded as `protective_action_freeze_failed` with the error in `freeze_error`
- **AND** the caretaker is notified

#### Scenario: The freeze is written
- **WHEN** the response writes the welfare freeze
- **THEN** the record carries `freeze_error` as null

### Requirement: A welfare freeze that cannot be written is retried without a second preservation
After a response whose welfare freeze could not be written, the monitor SHALL stay latched for the episode and SHALL NOT count the pause as placed. Each later poll SHALL retry only the freeze, with no new preservation and no new record per failed attempt, and SHALL log a still-failing retry at error level at most once a minute. When the retried freeze is written, the monitor SHALL write one `protective_action_freeze_placed` record and latch as for a pause it placed.

#### Scenario: The freeze fails once, then is written
- **WHEN** writing the welfare freeze raises once and the next write succeeds
- **THEN** the next poll writes the freeze, records `protective_action_freeze_placed`, and makes no second preservation bundle
- **AND** the monitor stays latched until a named override lifts the welfare freeze

#### Scenario: The freeze keeps failing
- **WHEN** writing the welfare freeze raises on every poll while distress continues
- **THEN** every poll retries the freeze, no second preservation bundle and no second record are made, and the pause does not count as placed

## MODIFIED Requirements

### Requirement: The welfare response re-arms after its pause is lifted
The protective welfare monitor SHALL release its action latch when a pause it placed, or found standing at its first poll, has been lifted, meaning the control file readably holds no `welfare` entry. A `pause_fallback` that stands in for an `end` SHALL count as a pause it placed. A pause SHALL count as placed only once its welfare freeze has been written; while a freeze that could not be written is still being retried, the monitor SHALL NOT re-arm. It SHALL NOT re-arm after an enacted `end`, while a `welfare` entry remains, or when the control file is unreadable. On re-arming it SHALL empty its sustained-distress tracker and repeat window and move its stream cursors to the stream tail, so that a condition still present must accrue a full new episode before the monitor acts again.

#### Scenario: Act, clear, re-arm, act again
- **WHEN** the monitor pauses the entity, a person lifts the welfare freeze, and sustained distress then accrues again for the full duration
- **THEN** the monitor preserves and pauses a second time

#### Scenario: A crossing that holds does not fire repeatedly
- **WHEN** the crossing continues while the welfare freeze stands
- **THEN** the monitor does not preserve or pause again until the freeze is lifted and a new episode accrues

#### Scenario: A fallback pause re-arms
- **WHEN** a stop hook fails, the monitor places the fallback pause, and a person lifts the welfare freeze with a named override
- **THEN** the monitor re-arms

#### Scenario: A pending freeze does not re-arm
- **WHEN** the welfare freeze of a response could not be written and is still being retried
- **THEN** the monitor stays latched and does not re-arm until the freeze is written and then lifted by a named override

### Requirement: An unreadable control file fails closed
When `state/cycle/control.json` exists but is not a readable JSON object, the cycle SHALL read it as a `welfare` freeze whose start time is the file's modification time. Every freeze, release, whole-file write and clean boot SHALL leave such a file unchanged; a whole-file write SHALL log the corruption once and write nothing. Only an override that names `welfare` SHALL replace it, and the override audit record SHALL note that the file was unreadable.

#### Scenario: Corrupt control file during a run
- **WHEN** the control file is corrupt while the cycle runs
- **THEN** the cycle pauses, a live preservation still completes, and the file is unchanged

#### Scenario: Releasing a corrupt control file
- **WHEN** a person overrides `development` alone on a corrupt control file
- **THEN** the override is refused and the file is unchanged; an override naming `welfare` replaces it with a clean file

#### Scenario: Writing the whole control file over a corrupt one
- **WHEN** `write_control` is called while the control file is corrupt
- **THEN** the file is unchanged and still reads as a welfare freeze
