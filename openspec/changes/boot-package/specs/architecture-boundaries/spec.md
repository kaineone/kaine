## ADDED Requirements

### Requirement: Module factories are independent
Each module factory SHALL live in its own module under `kaine.boot.factories`, and no factory module SHALL import another factory module. Helpers that several factories share SHALL live outside `kaine.boot.factories`. An import contract SHALL enforce this. `kaine.boot` SHALL re-export every factory and boot helper, so callers import from `kaine.boot` alone.

#### Scenario: A factory imports another factory
- **WHEN** one module under `kaine.boot.factories` imports another
- **THEN** the import contract check fails

#### Scenario: Callers keep importing from kaine.boot
- **WHEN** code imports a factory or boot helper from `kaine.boot`
- **THEN** it receives the object defined in the submodule
