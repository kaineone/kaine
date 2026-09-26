## ADDED Requirements

### Requirement: A preserved entity can be revived into a running cycle
The cycle SHALL accept a preservation bundle at start and run as that individual: the bundle's developmental stage SHALL be restored before the stage is resolved, every module the bundle captured SHALL be revived after the modules initialize and before the cognitive cycle starts, and modules enabled now but absent from the bundle SHALL start fresh. A bundle that cannot be read, or that captured a module that is not enabled, SHALL stop the start with a distinct exit code before the entity runs, never starting a lesser individual.

#### Scenario: Revive with one more faculty
- **WHEN** the cycle starts with a bundle and one module enabled that the bundle did not capture
- **THEN** every captured module's state is restored, the new module starts fresh, and the revived individual's stage and evidence are the preserved ones

#### Scenario: A captured faculty is missing
- **WHEN** the bundle captured a module that is not enabled
- **THEN** the start stops with the revive-refused exit code and the cognitive cycle never starts

### Requirement: The operator can preserve a running entity on request
The operator SHALL be able to request a preservation of the running entity. The cycle SHALL freeze the entity under its own freeze holder, preserve it with the configured encryption rules, report the result, and then either release its freeze or, when asked, stop cleanly while preserved. Each request SHALL be handled exactly once, and a failed preservation SHALL be reported without stopping the entity.

#### Scenario: Preserve and stop
- **WHEN** the operator requests a preservation with stop
- **THEN** the entity is frozen, a complete bundle is written, the result names it, and the cycle stops with the entity preserved

#### Scenario: A failed preservation keeps the entity running
- **WHEN** a requested preservation fails
- **THEN** the result reports the failure, the preserve freeze is released, and the entity keeps running
