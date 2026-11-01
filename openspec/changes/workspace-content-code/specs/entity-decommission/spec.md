## ADDED Requirements

### Requirement: Decommission removes the content-code checkpoint
The content-code checkpoint and the content-code artifacts in the entity's snapshots SHALL be among the entity's data locations. Decommission SHALL remove them and list them in the audit record, and a dry run SHALL list them.

#### Scenario: The checkpoint is removed
- **WHEN** an entity with a content-code checkpoint is decommissioned
- **THEN** the checkpoint no longer exists and the audit record names its location without its content

#### Scenario: A dry run lists it
- **WHEN** an operator runs a dry run for that entity
- **THEN** the checkpoint is listed and not removed
