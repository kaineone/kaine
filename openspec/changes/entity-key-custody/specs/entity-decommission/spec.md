## MODIFIED Requirements

### Requirement: Transferable backup before deletion
Decommission SHALL capture an encrypted, transferable backup of the entity's durable state before
any deletion, satisfying CAL Article 4.2(b). The backup SHALL bundle the Eidolon self-model, the
Lingua intent log, the Hypnos voice adapters, the latest fork snapshot, and an export (or explicit
volume-copy instructions) for the Mnemos and Empatheia Qdrant collections, plus a manifest
describing the entity, timestamp, divergence assessment, and contents. If the backup cannot be
completed, decommission SHALL abort without deleting anything. Under per-entity custody the backup SHALL
remain encrypted under the entity's data key with its escrow shares, and the trustees SHALL retain their
shares for as long as the backup exists, so the backup stays recoverable and transferable.

#### Scenario: Backup precedes deletion
- **WHEN** an operator runs the decommission CLI
- **THEN** an encrypted backup bundle with a manifest is written before any state is deleted

#### Scenario: Backup failure aborts
- **WHEN** the backup cannot be completed
- **THEN** no entity state is deleted and the CLI exits non-zero

#### Scenario: Backup stays recoverable under custody
- **WHEN** an entity under per-entity custody is decommissioned with a backup
- **THEN** the backup remains recoverable through the escrow trustees for as long as it exists
