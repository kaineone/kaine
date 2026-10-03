## ADDED Requirements

### Requirement: An unviable gestation ends early, with its data kept and a note written
During a gestation step, until it requests the birth or a disk-low preservation, the study runner SHALL poll the step's `state/lifecycle/gestation_viability.json`, ignoring a file older than the step. On an unviable verdict it SHALL stop the cycle gracefully without requesting a preservation bundle, record the step with outcome `failed:gestation_unviable` and the verdict's evidence, write `ENDED-NOTE.md` into the step directory describing the issue and the evidence, and halt the study for the operator. If stopping the cycle fails, the runner SHALL retry on the next poll; it SHALL NOT send SIGKILL. A verdict SHALL NOT stop or relabel a step whose birth has been requested. It SHALL NOT delete any study data.

#### Scenario: The runner ends an unviable gestation
- **WHEN** the gestation's viability file reports an unviable verdict
- **THEN** the cycle is stopped without a preservation request, the step is recorded as `failed:gestation_unviable`, `ENDED-NOTE.md` exists in the step directory, the study halts, and the step's data remains on disk

#### Scenario: A verdict after birth is ignored
- **WHEN** an unviable verdict file appears after the runner has requested the birth preservation
- **THEN** the cycle is not stopped by the watch and the step is not recorded as `failed:gestation_unviable`
