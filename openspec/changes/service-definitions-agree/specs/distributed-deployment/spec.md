## MODIFIED Requirements

### Requirement: Quadlet Qdrant healthcheck uses only tools in the image
`quadlet/kaine-qdrant.container` SHALL use a `bash /dev/tcp/127.0.0.1/6333` readiness probe, because the pinned Qdrant image ships neither `curl` nor `wget`.

#### Scenario: Qdrant healthcheck does not invoke curl
- **WHEN** `quadlet/kaine-qdrant.container` is inspected
- **THEN** `HealthCmd` does not contain `curl` or `wget`

#### Scenario: Qdrant healthcheck succeeds in the minimal image
- **WHEN** the Qdrant container starts from the Quadlet unit
- **THEN** the healthcheck exits 0 and the container is marked healthy
