## ADDED Requirements

### Requirement: Snapshot participants carry state that is not a module's
`ForkManager` SHALL accept registered snapshot participants, each with a name, an export hook, an import hook and a flag saying whether it imports before module state. A snapshot SHALL run each participant's export after capturing module states, into the snapshot's artifact directory for that participant, and record it under `metadata["participants"]`. A failed export SHALL remove the snapshot directory and raise.

#### Scenario: A failed export
- **WHEN** a participant's export raises during a snapshot
- **THEN** no snapshot directory is left behind and the error propagates

### Requirement: Participants restore in their declared order
Restore and revive SHALL run the import of every participant flagged to import before module state before any module's `deserialize`, and the others after. They SHALL refuse a snapshot whose metadata records a participant whose artifact is missing, and SHALL start the content code fresh with a warning when the snapshot predates it.

#### Scenario: The content code restores before the processors
- **WHEN** a snapshot with a content-code artifact is restored
- **THEN** the content code's import runs before the vision, audition and interoception modules deserialize

#### Scenario: A missing artifact is refused
- **WHEN** a bundle's metadata records a captured content code and the artifact is absent
- **THEN** revive refuses and names the missing artifact

#### Scenario: A preserved code is revived
- **WHEN** an entity with a trained content code is preserved and revived
- **THEN** the revived workspace forms the same code from the same slots

### Requirement: Forks copy participant artifacts and merges work from disk
A fork SHALL copy each participant's artifact directory into the child's own snapshot. A merge SHALL work from the parents' artifact directories on disk, with no live participant, so a merge requested from a process without a workspace behaves the same.

#### Scenario: Fork copies are independent
- **WHEN** a snapshot with a content-code artifact is forked twice
- **THEN** each child holds its own copy and changing one leaves the other unchanged

#### Scenario: A merge from the dashboard process
- **WHEN** the dashboard process merges two snapshots with content codes and `content_code_from = "a"`
- **THEN** the merged snapshot holds parent a's content-code artifact

### Requirement: Merge requires a choice of content code
When both parents carry a content code, merge SHALL refuse unless the caller passes `content_code_from = "a"` or `"b"`. The chosen parent's content-code artifact SHALL be copied whole, and every processor's top-down head base weights SHALL be taken from the same parent, overriding any other module-weight choice for those keys. The choice SHALL be recorded in the merged snapshot's metadata. Codes SHALL NOT be averaged.

#### Scenario: No choice
- **WHEN** two snapshots that both carry a content code are merged without `content_code_from`
- **THEN** merge refuses and names the missing choice

#### Scenario: Encoders and heads travel together, exactly
- **WHEN** they are merged with `content_code_from = "b"`
- **THEN** the merged content-code artifact equals parent b's byte for byte, and the vision, audition and interoception head base weights equal parent b's exactly
