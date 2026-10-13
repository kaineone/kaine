# Spec Delta

## ADDED Requirements

### Requirement: Decommission removes only the entity's own subdirectory in shared volumes
Decommission SHALL back up and then delete the entity's own subdirectory in the organ-adapters and trainer-jobs volumes, SHALL keep every other entity's subdirectory untouched, and SHALL attribute any legacy root-level entry only from the entity's own records, keeping what it cannot attribute and listing it as kept.

#### Scenario: Another entity's files survive
- **WHEN** an entity is decommissioned while a study line has adapters and jobs in the same volumes
- **THEN** the entity's subdirectory is in the backup and then gone, and the study line's subdirectory is unchanged

#### Scenario: Unfinished jobs leave nothing behind
- **WHEN** the entity has an unfinished job-queue job in the shared jobs volume
- **THEN** that job, with its training pairs, is backed up and then deleted with the entity's subdirectory
