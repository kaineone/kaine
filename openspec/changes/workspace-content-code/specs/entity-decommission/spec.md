## ADDED Requirements

### Requirement: Decommission removes the content-code checkpoint
The content-code checkpoint SHALL be one of the entity's data locations. Decommission SHALL remove it and list it in the audit record, and a dry run SHALL list it.

#### Scenario: The checkpoint is removed
- **WHEN** an entity with a content-code checkpoint is decommissioned
- **THEN** the checkpoint no longer exists and the audit record names its location without its content

#### Scenario: A dry run lists it
- **WHEN** an operator runs a dry run for that entity
- **THEN** the checkpoint is listed and not removed
