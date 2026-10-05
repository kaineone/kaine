## ADDED Requirements

### Requirement: Organ probes authenticate
Every KAINE probe of a protected organ endpoint (`/v1/models`, `/props`, `/slots`, `/lora-adapters`) SHALL send `Authorization: Bearer <key>` when a model-server API key is configured, resolved through `kaine.defaults.model_server_api_key`. A probe SHALL NOT report an empty or absent state because its unauthenticated request was refused.

#### Scenario: Preflight lists resident models on a keyed organ
- **WHEN** the preflight resident-models probe runs and a model-server key is configured
- **THEN** its `/v1/models` request carries the bearer key

#### Scenario: No key configured
- **WHEN** no model-server key is configured
- **THEN** the probe sends no `Authorization` header
