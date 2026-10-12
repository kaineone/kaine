## ADDED Requirements

### Requirement: Development progress travels with the entity
A preservation bundle SHALL carry the development progress and readout files that sit beside the stage file, and a revive SHALL restore them beside the stage file it writes, so an entity revived into a fresh state root keeps its awake time and readout progress. The viability verdict file SHALL NOT be bundled.

#### Scenario: Revive restores development progress
- **WHEN** a gestating being with `gestation_progress.json` beside its stage file is preserved and revived into an empty state root
- **THEN** the revived state root holds the same `gestation_progress.json`

#### Scenario: No development files, no development member
- **WHEN** an entity with no development files is preserved
- **THEN** the bundle has no `gestation/` member and revive restores nothing for it
