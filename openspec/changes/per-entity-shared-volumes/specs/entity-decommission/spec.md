# Spec Delta

## ADDED Requirements

### Requirement: Decommission removes only the entity's own subdirectory in shared volumes
Decommission SHALL back up and then delete the entity's own subdirectory in the organ-adapters and trainer-jobs volumes, SHALL keep every other entity's subdirectory untouched, and SHALL attribute any legacy root-level entry only from the entity's own records, keeping what it cannot attribute and listing it as kept.

#### Scenario: Another entity's files survive
- **WHEN** an entity is decommissioned while a study line has adapters and jobs in the same volumes
- **THEN** the entity's subdirectory is in the backup and then gone, and the study line's subdirectory is unchanged

#### Scenario: Owner records disagree
- **WHEN** a job sits under the entity's subdirectory but its description names another entity
- **THEN** the job is kept, not deleted, and flagged in the run's output and audit record

#### Scenario: Unfinished jobs leave nothing behind
- **WHEN** the entity has an unfinished job-queue job in the shared jobs volume
- **THEN** decommission cancels and waits for it inside the entity's subdirectory first, then backs it up and deletes it with its training pairs
