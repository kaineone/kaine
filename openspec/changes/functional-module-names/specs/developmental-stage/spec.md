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
