## ADDED Requirements

### Requirement: An unviable stop verifies that the kept state is restartable

After the child of an unviable developmental step exits, the study runner SHALL read the step's resume checkpoint under the configured encryption and SHALL record `state_restartable` and the checkpoint's timestamp in the step record. The state is restartable when the checkpoint exists, decrypts, parses, and carries the step's entity identity, and the stage file still records the developmental phase.

#### Scenario: Restartable state recorded

- **WHEN** an unviable step's child exits after SIGTERM and its checkpoint is present and matches the entity identity
- **THEN** the step record has `state_restartable == true` and the checkpoint timestamp

#### Scenario: A plain start resumes the stopped entity

- **WHEN** the cycle is started plainly on the state tree an unviable stop left
- **THEN** it resumes module state from the checkpoint with the same entity identity and developmental progress

### Requirement: An unviable stop without a restartable state halts the study as critical

If the kept state is not restartable, the runner SHALL record the outcome `failed:development_unviable_state_incomplete`, SHALL raise `StudyCritical`, and SHALL NOT start any later step. It SHALL NOT delete or modify the step directory.

#### Scenario: Missing checkpoint

- **WHEN** an unviable step's child exits and no readable checkpoint exists
- **THEN** the step is recorded as `failed:development_unviable_state_incomplete`, the study halts as critical, and the step directory is unchanged

### Requirement: The unviable note states the entity's status under the license

`ENDED-NOTE.md` for an unviable step SHALL state that the entity's state is kept and restartable from its checkpoint, that under the Cognitive Architecture License a restartable saved state is the entity, that the directory must not be deleted by hand, and that removal goes only through the decommission command.

#### Scenario: Note carries the license section

- **WHEN** the runner writes `ENDED-NOTE.md` for an unviable step with a restartable state
- **THEN** the note contains the checkpoint timestamp, the license statement and the decommission instruction
