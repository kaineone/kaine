## ADDED Requirements

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
