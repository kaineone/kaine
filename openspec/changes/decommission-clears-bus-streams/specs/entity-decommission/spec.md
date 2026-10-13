## ADDED Requirements

### Requirement: Decommission clears the entity's bus streams
Decommission SHALL delete every event-bus stream that carries the entity's
traffic, by exact stream name: the streams in the bus registry, the produced
streams the evaluation registry lists, and the cycle control stream, each under
both its old and its new module name. It SHALL NOT delete keys that are not
listed streams.

#### Scenario: Entity streams are deleted
- **WHEN** an entity is decommissioned and its bus holds module streams under old and new names
- **THEN** every one of those streams is deleted and reported as cleared

#### Scenario: Unrelated keys are kept
- **WHEN** the bus database also holds a key that is not a listed stream
- **THEN** decommission leaves that key in place
