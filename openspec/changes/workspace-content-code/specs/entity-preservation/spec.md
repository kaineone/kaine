## ADDED Requirements

### Requirement: Snapshots, forks and revive carry the content code
The workspace SHALL register a snapshot participant `workspace_content_code` whose artifact export and import hooks are run by snapshot and restore as module hooks are. A snapshot whose export fails SHALL NOT be saved. A fork SHALL copy the parent's artifact into its own snapshot. Revive SHALL install the artifact, SHALL refuse a snapshot that records a captured code with its artifact missing, and SHALL start a fresh code with a warning when the snapshot predates the code.

#### Scenario: A preserved code is revived
- **WHEN** an entity with a trained content code is preserved and revived
- **THEN** the revived workspace forms the same code from the same slots

#### Scenario: A missing artifact is refused
- **WHEN** a bundle's metadata records a captured content code and the artifact is absent
- **THEN** revive refuses and names the missing artifact

### Requirement: Merge requires a choice of content code
When both parents carry a content code, merge SHALL refuse unless the caller passes `content_code_from = "a"` or `"b"`. The chosen parent's encoders and every processor's top-down head SHALL then be taken together, and the choice SHALL be recorded in the merged snapshot's metadata. Codes SHALL NOT be averaged.

#### Scenario: No choice
- **WHEN** two snapshots that both carry a content code are merged without `content_code_from`
- **THEN** merge refuses and names the missing choice

#### Scenario: Encoders and heads travel together
- **WHEN** they are merged with `content_code_from = "b"`
- **THEN** the merged snapshot holds b's encoders and b's vision, audition and interoception heads
