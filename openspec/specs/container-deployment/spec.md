# container-deployment Specification

## Purpose
How the runtime image and its Compose and Quadlet units mount state, so a first bring-up on fresh volumes is race free and no container creates an anonymous volume.

## Requirements

### Requirement: First bring-up on an empty volume is race free
The runtime image SHALL contain no files or directories under `/app/state` other than the directory itself, so that two containers mounting a fresh state volume at once have no content to copy into it. The directory SHALL remain owned by the runtime user so a fresh volume inherits that owner.

#### Scenario: Image state tree is empty
- **WHEN** the Dockerfile is read
- **THEN** it creates `/app/state` and no path beneath it

### Requirement: No anonymous volumes
Every Compose service built from the runtime image SHALL mount a named volume at each path the image declares with `VOLUME`, and so SHALL the Quadlet dashboard unit, so that starting a container never creates an anonymous volume.

#### Scenario: Dashboard mounts the models volume read-only
- **WHEN** the dashboard service is read from `compose/kaine.yml` and `quadlet/kaine-dashboard.container`
- **THEN** each mounts the models volume at `/models` read-only
