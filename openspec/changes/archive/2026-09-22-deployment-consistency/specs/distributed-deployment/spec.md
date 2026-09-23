## ADDED Requirements

### Requirement: Quadlet cycle and Nexus units can reach the Redis bus
`quadlet/kaine-cycle.container` and `quadlet/kaine-nexus.container` SHALL set `Environment=KAINE_REDIS_URL=redis://:${KAINE_REDIS_PASSWORD}@kaine-redis:6379/0` so the in-container processes connect to the Redis service by container name, matching `compose/kaine.yml`.

#### Scenario: Cycle container has Redis URL
- **WHEN** `quadlet/kaine-cycle.container` is inspected
- **THEN** it contains `KAINE_REDIS_URL` pointing to `kaine-redis:6379/0`

#### Scenario: Nexus container has Redis URL
- **WHEN** `quadlet/kaine-nexus.container` is inspected
- **THEN** it contains `KAINE_REDIS_URL` pointing to `kaine-redis:6379/0`

### Requirement: Quadlet Qdrant healthcheck uses only tools in the image
`quadlet/kaine-qdrant.container` SHALL use a `bash /dev/tcp/127.0.0.1/6333` readiness probe, because the `qdrant:v1.18.0` image ships neither `curl` nor `wget`.

#### Scenario: Qdrant healthcheck does not invoke curl
- **WHEN** `quadlet/kaine-qdrant.container` is inspected
- **THEN** `HealthCmd` does not contain `curl` or `wget`

#### Scenario: Qdrant healthcheck succeeds in the minimal image
- **WHEN** the Qdrant container starts from the Quadlet unit
- **THEN** the healthcheck exits 0 and the container is marked healthy

### Requirement: Redis memory cap is consistent across deployment files
The Redis `--maxmemory` value SHALL be identical in `compose/kaine.yml`, `compose/redis.yml`, and `quadlet/kaine-redis.container`.

#### Scenario: Compose and Quadlet Redis caps match
- **WHEN** the three deployment files are compared
- **THEN** they all specify the same `--maxmemory` value
