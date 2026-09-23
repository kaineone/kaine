## ADDED Requirements

### Requirement: Redis bootstrap documentation reflects the unified memory cap
`scripts/redis-bootstrap.sh` and any Redis deployment documentation SHALL use the same `--maxmemory` value as `compose/kaine.yml` and `quadlet/kaine-redis.container`.

#### Scenario: Bootstrap script cap matches deployment files
- **WHEN** `scripts/redis-bootstrap.sh` is inspected
- **THEN** its `--maxmemory` argument matches the value in `compose/kaine.yml`
