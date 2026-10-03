# ignition-log Specification

## Purpose
The ignition log is an optional, content-free research record of every workspace broadcast. It places each ignition in the film programme (item, offset, paused) and keeps the entry ids, the run id and the broadcast time, so the module-ignition study can compare ignitions across viewings without recording what the being perceived or thought.

## Requirements

### Requirement: Each workspace broadcast is recorded with its place in the programme
When the ignition log is enabled, the cycle SHALL record every successful workspace broadcast with: the run id and a sequence number, the tick index, the broadcast's bus entry id, its wall and monotonic time, the programme position at that instant (item index, order, title, offset, and whether the programme was paused), the audio feed's own position when it reports one, the salience scores and inhibition, and each coalition member's entry id, source, type, salience and original timestamp. The record SHALL contain no event payloads. The log SHALL ship disabled and SHALL be encrypted at rest when state encryption is on.

#### Scenario: A broadcast during a film
- **WHEN** the log is enabled and a coalition is broadcast 12.5 s into the second film
- **THEN** one record holds item order 2, offset 12.5 s, the members' ids and timestamps, and no payload

#### Scenario: A failed broadcast
- **WHEN** publishing a broadcast fails
- **THEN** no record is written for it

### Requirement: The entity never learns its place in the programme
The programme position SHALL be taken in-process at the cycle layer and written only to the ignition log. It SHALL NOT be added to the workspace broadcast, published on the bus, or delivered to any module, and an error in the ignition log SHALL NOT affect the cognitive cycle.

#### Scenario: Position stays out of the workspace
- **WHEN** the log is enabled and a broadcast is recorded
- **THEN** the broadcast published on the bus is identical to the one published with the log disabled

#### Scenario: A log error
- **WHEN** the ignition log raises while recording
- **THEN** the tick completes normally and the error is logged

### Requirement: The ignition log is the workspace-graph record and only the operator deletes it
The ignition log SHALL be the record of the global workspace graph kept by research runs: one row per successful broadcast, at full rate, never sampled. It is kept for the paper analysis and then as world-model training data. It SHALL never be deleted or purged automatically; its sink SHALL use no retention period, and deletion SHALL be an operator action.

#### Scenario: Old files are kept
- **WHEN** the ignition log starts while files from earlier days exist in its directory
- **THEN** none of them is removed

#### Scenario: Every broadcast is recorded
- **WHEN** N broadcasts succeed with the log enabled
- **THEN** the log holds N rows
