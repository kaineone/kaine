## ADDED Requirements

### Requirement: Decommission backs up and removes the conversation collection
Decommission SHALL include the encrypted conversation store under `state/episodic_memory/conversation/<collection_prefix>/`, for each of the entity's prefixes, in the transferable backup. It SHALL then delete it with the other episodic memory collections, resolving the kind through `kaine/memory_kinds.py`. A conversation store that cannot be read SHALL fail the backup before anything is deleted.

#### Scenario: The conversation store is backed up and removed
- **WHEN** an entity with conversation traces is decommissioned
- **THEN** its conversation store is in the backup and is gone from the state tree afterwards
