## ADDED Requirements

### Requirement: An unviable gestation ends early, with its data kept and a note written
During a gestation step, the study runner SHALL poll the step's `state/lifecycle/gestation_viability.json`. On an unviable verdict it SHALL stop the cycle gracefully without requesting a preservation bundle, record the step with outcome `failed:gestation_unviable` and the verdict's evidence, write `ENDED-NOTE.md` into the step directory describing the issue and the evidence, and halt the study for the operator. It SHALL NOT delete any study data.

#### Scenario: The runner ends an unviable gestation
- **WHEN** the gestation's viability file reports an unviable verdict
- **THEN** the cycle is stopped without a preservation request, the step is recorded as `failed:gestation_unviable`, `ENDED-NOTE.md` exists in the step directory, the study halts, and the step's data remains on disk
