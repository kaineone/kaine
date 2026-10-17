## ADDED Requirements

### Requirement: A rolling resume checkpoint holds module state across plain restarts
The cycle SHALL keep exactly one resume checkpoint per state tree, at `checkpoint/checkpoint.json` beside the stage file. The checkpoint SHALL hold each enabled module's `serialize()` state and the entity identity, SHALL be written through the process-wide state encryptor, and SHALL replace the previous checkpoint atomically. It SHALL leave out the self-model, episodic memory, social cognition and world model modules, whose own stores persist them, and the bus cursors of the interoception, embodiment and sequence modules. The cycle SHALL write it after every 60 s of awake entity time and once at a clean shutdown, and SHALL NOT write it periodically while the cycle is frozen or asleep, nor at shutdown while the sleep module is asleep. The checkpoint SHALL carry the self-model module's drift count, which its own file does not hold. A module whose `serialize()` fails SHALL be left out of that write with a warning naming it, and SHALL start fresh after a restart. The cycle SHALL NOT write the shutdown checkpoint when the cognitive cycle ended with an error.

#### Scenario: Many writes leave one checkpoint
- **WHEN** the checkpoint has been written many times
- **THEN** the checkpoint directory holds exactly one checkpoint file

#### Scenario: The checkpoint is encrypted when encryption is configured
- **WHEN** `[security.state_encryption]` is enabled with a key and the checkpoint is written
- **THEN** the file on disk is an encryption envelope and contains no plaintext module state

#### Scenario: Shutdown writes a checkpoint
- **WHEN** the cycle shuts down cleanly while awake
- **THEN** one checkpoint holding the module state at shutdown is on disk

#### Scenario: No periodic write while frozen or asleep
- **WHEN** 60 s of entity time pass with the cycle frozen or asleep
- **THEN** no periodic checkpoint is written

### Requirement: A plain start resumes module state from a matching checkpoint
On a start without `--revive`, after the modules initialise and before the cognitive cycle starts, the cycle SHALL restore each checkpointed module that is enabled now through its `deserialize()`, but only when the checkpoint's entity id equals the state tree's entity id. The restore SHALL NOT record `revived_from`, set developmental files aside or change the identity. A missing checkpoint SHALL leave the modules fresh. An unreadable, undecryptable, malformed or other-entity checkpoint SHALL be ignored with one warning and the modules SHALL start fresh. A module absent from the checkpoint SHALL start fresh, and a checkpointed module not enabled now SHALL be skipped.

#### Scenario: A restart restores the same module state
- **WHEN** an entity with an adapted self-rhythm recovery time, raised affect drives and an active goal writes a checkpoint and a new process starts on the same state tree
- **THEN** the self-rhythm's log recovery time, the drive values and outcome counts and the goal ledger equal the values before the restart

#### Scenario: Another entity's checkpoint is ignored
- **WHEN** the checkpoint's entity id differs from the state tree's
- **THEN** one warning is logged and every module keeps its fresh state

#### Scenario: A corrupt checkpoint is ignored
- **WHEN** the checkpoint file cannot be decrypted or parsed
- **THEN** one warning is logged and every module keeps its fresh state

### Requirement: A revive wins over any checkpoint
A start with `--revive` SHALL NOT read the resume checkpoint. Before the revive starts, the cycle SHALL write a revive record and rename any checkpoint aside, and SHALL stop the start when it cannot. Once the revive has landed, the cycle SHALL write a fresh checkpoint of the revived state. A plain start SHALL ignore a checkpoint older than the revive record.

#### Scenario: A revive refused part way leaves no checkpoint to restore
- **WHEN** a revive changes some modules and is then refused
- **THEN** the old checkpoint is renamed aside and the next plain start restores nothing from it

#### Scenario: A stale checkpoint never overrides a revive
- **WHEN** a state tree holds a checkpoint and the entity is revived from a bundle, and the process then stops before its first periodic write
- **THEN** the next plain start restores the revived state, not the stale checkpoint

### Requirement: Decommission removes the resume checkpoint
Decommission SHALL back up and then delete the resume checkpoint directory with the other entity state.

#### Scenario: The checkpoint is backed up and deleted
- **WHEN** an entity with a resume checkpoint is decommissioned
- **THEN** the checkpoint is in the backup bundle and absent from the state tree
