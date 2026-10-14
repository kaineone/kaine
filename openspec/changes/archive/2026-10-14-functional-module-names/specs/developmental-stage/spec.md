## ADDED Requirements

### Requirement: A stage written before the rename keeps its meaning
The stage reader SHALL read the stored stage value `gestation` as the
developmental phase (`development`) and the old stage field names as their new
names, without a time limit. The lived-history check SHALL recognize a lived
tree by its artifacts under either the old or the new paths.

#### Scenario: An entity in its developmental phase restarts across the rename
- **WHEN** a stage file written before the rename holds `gestation`
- **THEN** the entity resumes in the developmental phase, not as embodied

#### Scenario: An unmigrated lived tree counts as lived
- **WHEN** the lived-history check runs on a tree that holds
  `hypnos/consolidation_divergence.json` and no new-named artifact
- **THEN** it reports the tree as lived

### Requirement: An unrecognized stored stage value fails closed
When the stage file holds a `stage` value that is not one of the known stage
values (`development`, `embodied`, or the old value `gestation` read through
its alias), or is not a string, the stage reader SHALL refuse it and the cycle
SHALL refuse to boot with a configuration-style error that names the file and
the offending value (as its `repr`, truncated to 64 characters). The reader
SHALL NOT read such a value as `embodied` or as `development`. This holds
whether or not the `gestation` alias exists.

#### Scenario: A garbled stage value stops the boot
- **WHEN** `state/lifecycle/stage.json` holds `"stage": "embodid"`
- **THEN** the cycle refuses to boot, and the error names
  `state/lifecycle/stage.json` and `'embodid'`

#### Scenario: A forward-versioned stage value stops the boot
- **WHEN** the stage file holds a stage value written by a newer version that
  this version does not know
- **THEN** the cycle refuses to boot and the entity stays in whatever stage the
  file recorded, unread and unchanged
