## ADDED Requirements

### Requirement: Decommission covers every location of the entity's data
Decommission SHALL act on every location of the entity's data within its configured state and data roots, its deployment's volumes and the stores the deployment uses, as listed in this change's design: it SHALL back up every location that holds Cognitive State before deleting anything, SHALL delete every location that holds this entity's content or operational state, and SHALL keep welfare records, audit records, content-free research metrics, earlier preservation bundles and other entities' data. Each location SHALL be resolved through the configuration and the module-rename table, not through hard-coded paths.

#### Scenario: The sqlite-vec memory store is backed up and deleted
- **WHEN** an entity using the sqlite-vec episodic-memory backend is decommissioned
- **THEN** its memory database is in the transferable backup and is gone from the state tree afterwards

#### Scenario: Welfare and audit records are kept
- **WHEN** an entity is decommissioned
- **THEN** its incident log, welfare action log, gray-zone welfare log, override audit, spawn acknowledgements and effectors audit log remain on disk unchanged

#### Scenario: Another entity's fork survives
- **WHEN** the fork root holds snapshots of this entity and of another entity
- **THEN** only this entity's snapshots are backed up and deleted, and the other entity's snapshots remain

#### Scenario: Nothing a later entity would inherit remains
- **WHEN** decommission completes
- **THEN** the identity file, the stage and developmental files and the run's operational files are gone, the identity file with its lineage is in the backup, and the entity's id is recorded in the audit record

### Requirement: Unreachable stores fail decommission
Decommission SHALL reach Qdrant and Redis with the credentials the cycle uses. If a store holding the entity's data cannot be reached or refuses authentication, decommission SHALL fail before deleting anything and SHALL NOT report success.

#### Scenario: Qdrant refuses authentication
- **WHEN** the Qdrant probe fails with an authentication error
- **THEN** no state is deleted and the CLI exits non-zero naming the store

#### Scenario: Redis refuses authentication
- **WHEN** the bus refuses the credentials
- **THEN** no state is deleted and the CLI exits non-zero naming the store

### Requirement: Content-free decommission audit record
Every decommission run that reaches the deletion step SHALL append one record to a kept audit log, holding when it ran, its outcome, which locations were deleted, kept and backed up, and the backup path, and SHALL NOT hold any of the entity's content.

#### Scenario: The audit record holds names only
- **WHEN** a decommission run completes, or fails after the deletion step has started
- **THEN** the audit log gains one record that lists the locations and outcome and contains none of the deleted content

### Requirement: Reminder of the written-notice duty
Before the typed confirmation, on every decommission path, the CLI SHALL print a reminder of the CAL Article 4.2(a) duty to give the Guardians written notice, adding the CAL Article 7.0 interim rule where no Guardian body has been established. The reminder SHALL NOT block the run, and the audit record SHALL note that it was shown.

#### Scenario: Reminder on a non-diverged entity
- **WHEN** an operator decommissions an entity that has not diverged
- **THEN** the written-notice reminder is printed before the confirmation and the audit record notes it was shown
