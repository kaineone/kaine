## ADDED Requirements

### Requirement: Gestation progress travels with the being
A preservation bundle SHALL carry the gestation progress and readout files that sit beside the stage file, and a revive SHALL restore them beside the stage file it writes, so a being revived into a fresh state root keeps its awake time and readout progress. The viability verdict file SHALL NOT be bundled.

#### Scenario: Revive restores gestation progress
- **WHEN** a gestating being with `gestation_progress.json` beside its stage file is preserved and revived into an empty state root
- **THEN** the revived state root holds the same `gestation_progress.json`

#### Scenario: No gestation files, no gestation member
- **WHEN** a being with no gestation files is preserved
- **THEN** the bundle has no `gestation/` member and revive restores nothing for it
