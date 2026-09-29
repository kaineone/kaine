## MODIFIED Requirements

### Requirement: Redis memory cap is consistent across deployment files
The Redis `--maxmemory` value SHALL come from the host variable `KAINE_REDIS_MAXMEMORY` with the same default, `4gb`, in `compose/kaine.yml`, `compose/redis.yml`, and `quadlet/kaine-redis.container`. The compose files SHALL use `${KAINE_REDIS_MAXMEMORY:-4gb}`. The Quadlet unit SHALL set the default with `Environment=KAINE_REDIS_MAXMEMORY=4gb` in its `[Service]` section and read an override from the `EnvironmentFile` it already loads (`compose/.env`), which systemd applies after `Environment=`. Every deployment file SHALL keep `--maxmemory-policy noeviction`.

#### Scenario: Compose and Quadlet Redis caps match
- **WHEN** the three deployment files are compared
- **THEN** they all take `--maxmemory` from `KAINE_REDIS_MAXMEMORY` with the default `4gb`
- **AND** they all specify `--maxmemory-policy noeviction`

#### Scenario: A host raises the cap
- **WHEN** `compose/.env` sets `KAINE_REDIS_MAXMEMORY=12gb`
- **THEN** the compose topology renders `--maxmemory 12gb`
