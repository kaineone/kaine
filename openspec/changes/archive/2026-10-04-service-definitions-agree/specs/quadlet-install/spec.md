## ADDED Requirements

### Requirement: Every service definition agrees
Each service defined in more than one place (the canonical compose stack, the standalone compose files, the quadlet units, and the native installer for Qdrant) SHALL use the same image and version, the same published host and container ports, and the same server arguments in every definition. A test SHALL fail when any of these differ.

#### Scenario: A pin changes in one place only
- **WHEN** the Qdrant image is bumped in one definition but not the others
- **THEN** the agreement test fails, naming the service, the files and both values

#### Scenario: A Redis flag differs
- **WHEN** a Redis server argument in the quadlet unit differs from the compose command
- **THEN** the agreement test fails
