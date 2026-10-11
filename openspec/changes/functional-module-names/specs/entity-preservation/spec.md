## ADDED Requirements

### Requirement: State written under old module names imports unchanged
Import of a preservation bundle, a snapshot or a fork sidecar SHALL map old
module keys, the manifest's `modules` list, the `gestation/` member directory,
stage values and stage field names to the new names, without a time limit.
Import SHALL NOT rewrite the bundle, its manifest or its hashes. An unmigrated
state tree (a fork root, an extracted bundle or the live tree before the boot
migration) SHALL be migrated by the same idempotent step that migrates the live
tree, which SHALL record every move so it can be reverted, and SHALL refuse to
proceed when an old and a new name both exist for one item.

#### Scenario: A bundle preserved before the rename is revived
- **WHEN** a bundle whose manifest lists `thymos`, `mnemos` and `phantasia` is
  imported
- **THEN** the Affect, Episodic memory and World model modules receive the
  state that was captured under the old keys, and the bundle's bytes are
  unchanged

#### Scenario: The migration is idempotent
- **WHEN** the state migration runs on a tree it has already migrated
- **THEN** it moves nothing

#### Scenario: An old and a new name both exist
- **WHEN** a state tree holds both `mnemos/` and `episodic_memory/`
- **THEN** the migration fails the boot and moves nothing
