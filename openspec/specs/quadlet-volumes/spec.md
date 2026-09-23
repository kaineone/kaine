# quadlet-volumes Specification

## Purpose
Define the Podman Quadlet volume units that persist KAINE state, evaluation data, models, and service data in the rootless production deployment path.

## Requirements

### Requirement: Quadlet volume units exist for every durable mount
The repository SHALL ship `.volume` units for every named volume referenced by the Quadlet `.container` units: `kaine-state.volume`, `kaine-models.volume`, `kaine-eval-data.volume`, `kaine-trajectory.volume`, `kaine-redis-data.volume`, and `kaine-qdrant-data.volume`.

#### Scenario: All referenced volumes have units
- **WHEN** `grep -h "Volume=kaine-" quadlet/*.container` is run
- **THEN** every referenced `kaine-*.volume` name has a matching file in `quadlet/`

#### Scenario: Volume units are copied during install
- **WHEN** an operator follows `quadlet/README.md`
- **THEN** the install step copies `*.volume` units alongside `*.container` and `*.network` units
