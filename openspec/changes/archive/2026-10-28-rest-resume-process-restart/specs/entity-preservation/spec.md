## MODIFIED Requirements

### Requirement: A rolling resume checkpoint holds module state across plain restarts
The cycle SHALL keep exactly one resume checkpoint per state tree, at `checkpoint/checkpoint.json` beside the stage file. The checkpoint SHALL hold each enabled module's `serialize()` state and the entity identity, SHALL be written through the process-wide state encryptor, and SHALL replace the previous checkpoint atomically. It SHALL leave out the self-model, episodic memory, social cognition and world model modules, whose own stores persist them, and the bus cursors of the interoception, embodiment and sequence modules. The cycle SHALL write it after every 60 s of awake entity time and once at a clean shutdown, and SHALL NOT write it periodically while the cycle is frozen or asleep, nor at shutdown while the sleep module is asleep. The one exception is a `state_cycle` rest: while it runs the cycle SHALL replace only the sleep module's `state_cycle` entry inside the existing checkpoint, under the same encryption, entity check and revive rule, and every other module's entry SHALL stay as the last awake write left it. The checkpoint SHALL carry the self-model module's drift count, which its own file does not hold. A module whose `serialize()` fails SHALL be left out of that write with a warning naming it, and SHALL start fresh after a restart. The cycle SHALL NOT write the shutdown checkpoint when the cognitive cycle ended with an error.

#### Scenario: Many writes leave one checkpoint
- **WHEN** the checkpoint has been written many times
- **THEN** the checkpoint directory holds exactly one checkpoint file

#### Scenario: The checkpoint is encrypted when encryption is configured
- **WHEN** `[security.state_encryption]` is enabled with a key and the checkpoint is written
- **THEN** the file on disk is encrypted and a rest update stays encrypted too

#### Scenario: Shutdown writes a checkpoint
- **WHEN** the cycle shuts down cleanly while awake
- **THEN** one checkpoint holding the module state at shutdown is on disk

#### Scenario: No periodic write while frozen or asleep
- **WHEN** 60 s of entity time pass with the cycle frozen or asleep
- **THEN** no periodic checkpoint is written

#### Scenario: A rest touches only the sleep entry
- **WHEN** a `state_cycle` rest runs for its whole length after an awake checkpoint
- **THEN** every module's entry except the sleep module's `state_cycle` is identical to the awake write
