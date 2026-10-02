## ADDED Requirements

### Requirement: Infrastructure never deletes fork snapshots

`ForkManager` SHALL NOT delete any snapshot directory under its root. Taking,
forking or merging a snapshot SHALL leave every existing snapshot in place,
however many there are. Deleting an entity's state SHALL happen only through the
CAL-gated decommission path.

`[lifecycle].max_snapshots_retained` SHALL NOT appear in the shipped
configuration. A configuration that still sets it SHALL load without error. When
the value is greater than 0, the component that builds the fork manager SHALL log
a warning that the key is ignored and that snapshots are never deleted by
infrastructure.

#### Scenario: Many snapshots are all kept

- **WHEN** more than 64 snapshots are taken under one fork root
- **THEN** every snapshot directory remains on disk and is listed

#### Scenario: A legacy retention key is ignored with a warning

- **WHEN** the operator config sets `[lifecycle].max_snapshots_retained = 2` and
  the fork manager is built
- **THEN** a warning names the ignored key
- **AND** taking more than two snapshots deletes none of them
