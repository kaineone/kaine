## ADDED Requirements

### Requirement: Organ healthcheck probes the public liveness endpoint
The organ container's healthcheck SHALL probe llama-server's `/health` endpoint, in both `compose/kaine.yml` and `quadlet/kaine-model-server.container`, so it passes when the organ requires an API key and never needs the key on its command line.

#### Scenario: Healthcheck with an API key configured
- **WHEN** the organ runs with `--api-key` and has loaded its model
- **THEN** the healthcheck exits 0 and the container is marked healthy

#### Scenario: Compose and Quadlet agree
- **WHEN** the two deployment files are compared
- **THEN** both organ healthchecks curl `http://127.0.0.1:8080/health`
