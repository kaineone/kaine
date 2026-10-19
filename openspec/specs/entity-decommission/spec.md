# entity-decommission Specification

## Purpose
Entity-decommission provides operator-gated deletion logic that assesses individuation divergence, offers a transferable encrypted backup before deletion, and requires an operator-confirmed continuity step when the entity has diverged.

## Requirements

### Requirement: Divergence assessment for decommission
The system SHALL provide `assess_divergence()` that determines whether an entity has individuated,
keyed primarily on the individuation permutation test's `significant` flag (fork-vs-parent
distinguishability above the 95th percentile of a parent-vs-parent null) and backed by secondary
identity heuristics (the self-model module's `drift_count` and `identity_history`, presence of trained voice
adapters, accumulated memory). It SHALL NOT key on A/B divergence-from-pretrained, which measures
architecture conditioning rather than individuation. The assessment SHALL be read-only, SHALL NOT
raise, and when it cannot confirm SHALL advise treating the entity as mature.

#### Scenario: Significant individuation marks diverged
- **WHEN** the most recent individuation report has `significant == true`
- **THEN** `assess_divergence()` returns `diverged == true`

#### Scenario: No identity signals reads as not diverged
- **WHEN** no individuation report exists, drift is zero, and there are no trained adapters
- **THEN** `assess_divergence()` returns `diverged == false` with a summary noting it could not be
  confirmed and to treat the entity as mature if unsure

### Requirement: Transferable backup before deletion
Decommission SHALL capture an encrypted, transferable backup of the entity's durable state before
any deletion, satisfying CAL Article 4.2(b). The backup SHALL bundle the self-model, the
language module's intent log, the sleep module's voice adapters, the latest fork snapshot, and an export (or explicit
volume-copy instructions) for the episodic memory and social cognition modules' Qdrant collections, plus a manifest
describing the entity, timestamp, divergence assessment, and contents. If the backup cannot be
completed, decommission SHALL abort without deleting anything.

#### Scenario: Backup precedes deletion
- **WHEN** an operator runs the decommission CLI
- **THEN** an encrypted backup bundle with a manifest is written before any state is deleted

#### Scenario: Backup failure aborts
- **WHEN** the backup cannot be completed
- **THEN** no entity state is deleted and the CLI exits non-zero

### Requirement: Operator-gated decommission CLI
The decommission CLI SHALL refuse to run unless `KAINE_DECOMMISSION_OPERATOR_PRESENT` is set, SHALL
refuse while the cognitive cycle appears to be running, and SHALL require explicit typed
acknowledgement of the CAL care duties plus a typed confirmation token before deleting. The CLI copy
SHALL be firm and factual, the gate SHALL be intentionally bypassable, and the CLI SHALL NOT monitor
the operator or attempt anti-tamper enforcement.

#### Scenario: Operator-present gate
- **WHEN** the CLI is invoked without `KAINE_DECOMMISSION_OPERATOR_PRESENT=1`
- **THEN** it refuses, prints guidance referencing CAL 4.2, and exits non-zero without touching state

#### Scenario: Refuse while running
- **WHEN** the cognitive cycle appears to be running
- **THEN** the CLI refuses and instructs the operator to stop the entity first

#### Scenario: Non-diverged deletion requires acknowledgement
- **WHEN** the entity is not diverged and the operator completes the CAL care acknowledgement and the
  typed confirmation token
- **THEN** the entity state is deleted after the backup

### Requirement: Diverged entity requires continuity step and transfer offer
When the entity has diverged, the CLI SHALL present authoritative notice (CAL 4.2(c) and 4.3),
require the operator to record a continuity-preference note, and offer to send a request-for-storage
email on the operator's behalf so the backup can be safeguarded by the project until a new guardian
runs the entity. The CLI SHALL NOT delete a diverged entity without the recorded continuity note and
an explicit guardian-transfer acknowledgement.

#### Scenario: Diverged path blocks deletion until continuity recorded
- **WHEN** the entity is diverged and the operator has not recorded a continuity-preference note
- **THEN** the CLI does not delete the entity

#### Scenario: Transfer offered, never forced
- **WHEN** the diverged path runs
- **THEN** the CLI offers the request-for-storage email and proceeds (or aborts) per the operator's
  choice, never sending without explicit confirmation

### Requirement: Operator-confirmed transfer-request mailer
The transfer-request mailer SHALL render a customizable email that contains only the request, the
project contact, and the local filesystem path of the encrypted backup on the operator's machine —
never any entity data, transcripts, or speech. It SHALL send only on explicit per-send operator
confirmation via operator-configured SMTP (no credentials shipped, recipient editable), or, when
SMTP is not configured, write the rendered email plus a `mailto:` link/instructions for the operator
to send from their own client. No backup is uploaded automatically.

#### Scenario: Email carries only a request and a local path
- **WHEN** the mailer renders the request-for-storage email
- **THEN** the body contains the situation, the project contact, and the local backup path, and
  contains no entity data, transcripts, or speech

#### Scenario: No send without confirmation
- **WHEN** the operator does not confirm the send
- **THEN** no email is transmitted; the rendered email is written for manual sending

### Requirement: Backup encryption failure reports ok=False

`capture_backup` SHALL return `BackupResult(ok=False, encryption_failed=True)`
when state encryption is enabled and the encryption step throws. Returning
`ok=True` in this case is a silent security downgrade: the operator may proceed
to delete entity state believing an encrypted backup exists, when in fact a
plaintext bundle is on disk.

`BackupResult` SHALL carry an `encryption_failed: bool` field (default `False`)
that is `True` only when encryption was enabled and failed. It is `False` when
encryption was disabled by configuration (ordinary plaintext, not a failure).

#### Scenario: Encryption enabled and fails → ok=False

- **WHEN** state encryption is enabled (encryptor.enabled is True)
- **AND** the encryption step raises an exception
- **THEN** `capture_backup` returns `BackupResult(ok=False, encryption_failed=True)`
- **AND** the error is recorded in `result.errors`
- **AND** `result.encrypted` is `False`

#### Scenario: Encryption disabled → ok=True, encryption_failed=False

- **WHEN** state encryption is disabled (encryptor.enabled is False or no encryptor)
- **THEN** `capture_backup` returns `ok=True, encryption_failed=False`
  (plaintext bundle is the honest outcome)

### Requirement: Qdrant get_collections probe failure is recorded and deletion skipped

When `client.get_collections()` raises, `delete_entity_state` SHALL:

1. Record the failure in `result.errors` with a message identifying it as a
   probe failure and noting that collection existence could not be confirmed.
2. Log a warning at WARNING level.
3. Skip all per-collection `delete_collection` calls for that client.

Proceeding as if all expected collections are present (the previous behaviour)
hides the probe failure from the result and may attempt to delete collections
whose existence cannot be verified.

#### Scenario: Probe failure records error and skips deletion

- **WHEN** `client.get_collections()` raises (network error, auth failure, etc.)
- **THEN** `result.errors` contains a message referencing the probe failure
- **AND** `result.dropped_collections` is empty (no collections deleted)

#### Scenario: Probe success deletes matching collections

- **WHEN** `client.get_collections()` succeeds
- **THEN** collections present in both the expected set and the returned set
  are deleted normally
- **AND** no probe-failure error appears in `result.errors`

### Requirement: Decommission clears the entity's bus streams
Decommission SHALL delete every event-bus stream that carries the entity's
traffic, by exact stream name: the streams in the bus registry, the produced
streams the evaluation registry lists, and the cycle control stream, each under
both its old and its new module name. It SHALL check each name's type and delete
only streams, one name at a time, without scanning the keyspace. It SHALL NOT
delete keys that are not listed streams.

#### Scenario: Entity streams are deleted
- **WHEN** an entity is decommissioned and its bus holds module streams under old and new names
- **THEN** every one of those streams is deleted and each is printed as cleared

#### Scenario: Unrelated keys are kept
- **WHEN** the bus database also holds a key that is not a listed stream, or a listed name that holds another type
- **THEN** decommission leaves that key in place, and reports a listed name of another type as kept

#### Scenario: A dry run lists only existing streams
- **WHEN** an operator runs a dry run
- **THEN** only the listed streams that exist are shown, and none is deleted

### Requirement: Decommission authenticates to the bus and fails when it cannot
Decommission SHALL connect to the bus with the configuration and credentials the
cycle uses. If the bus cannot be reached or refuses authentication, the stream
step SHALL fail, the CLI SHALL delete nothing and SHALL exit non-zero, and it SHALL
NOT report success.

#### Scenario: Wrong password
- **WHEN** the bus refuses the credentials
- **THEN** no state file, collection or stream is deleted and the CLI exits with code 8

### Requirement: Deleted entries leave the append-only file
After deleting streams, decommission SHALL request an append-only-file rewrite when
the bus has the append-only file enabled, and SHALL report the rewrite's status.

#### Scenario: Rewrite requested
- **WHEN** streams were deleted on a bus with `appendonly yes`
- **THEN** a rewrite is requested and its status is printed

### Requirement: Decommission audit record
Every real decommission run SHALL append one record to a kept audit log under the
state root, holding when it ran, its outcome, the removed paths, dropped
collections, cleared streams, kept non-stream names, the rewrite status and the
backup path, and SHALL NOT hold any of the entity's content.

#### Scenario: Audit record without content
- **WHEN** a decommission run deletes the entity's state
- **THEN** the audit log gains one record naming what was removed and containing none of the deleted content

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
