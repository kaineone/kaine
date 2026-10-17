## ADDED Requirements

### Requirement: The self-rhythm identity persists across plain restarts
The developmental readout SHALL store the self-rhythm identity in `self_rhythm_identity.json` beside its readout file. On a boot that is not a revive, the readout SHALL adopt a valid stored identity into the self-rhythm before it builds the key for its progress and baseline files. On a revive boot the identity restored from the bundle SHALL be kept and SHALL replace the stored one. On every start the readout SHALL write the identity it uses. A missing, unreadable or malformed file SHALL leave the current identity in place, and a malformed file SHALL be logged and rewritten. Progress saved under a different key SHALL still be ignored.

#### Scenario: A plain restart keeps the developmental progress
- **WHEN** a readout for an entity with a self-rhythm has saved 7200 s of awake time and two consecutive passes, and a new readout is constructed on the same state directory with a freshly built self-rhythm that drew a new identity
- **THEN** the new readout adopts the stored identity and starts from 7200 s of awake time and two consecutive passes

#### Scenario: A revive keeps the bundle's identity
- **WHEN** the state directory stores identity A and the readout is constructed on a revive boot whose self-rhythm holds identity B
- **THEN** the readout keys its files with identity B and the stored file holds B afterwards

#### Scenario: Another entity's progress is still ignored
- **WHEN** the saved progress carries a key for a different seed or identity than the one the readout uses
- **THEN** the readout starts from zero awake time and zero passes

#### Scenario: A malformed identity file is replaced
- **WHEN** `self_rhythm_identity.json` does not hold a valid identity
- **THEN** the readout keeps the self-rhythm's current identity, logs a warning and rewrites the file

### Requirement: Decommission removes the stored self-rhythm identity
Decommission SHALL back up and then delete `self_rhythm_identity.json` with the other developmental-phase files, so a later entity in the same state tree never adopts it.

#### Scenario: Decommission lists the identity file
- **WHEN** decommission builds its locations for a tree whose lifecycle directory holds `self_rhythm_identity.json`
- **THEN** the developmental location backs it up and deletes it
