## MODIFIED Requirements

### Requirement: Redis bootstrap documentation reflects the unified memory cap
`scripts/redis-bootstrap.sh`, the native `redis.conf` writer in `scripts/lib/native-services.sh`, and any Redis deployment documentation SHALL use the same memory cap as `compose/kaine.yml` and `quadlet/kaine-redis.container`: the value of `KAINE_REDIS_MAXMEMORY`, defaulting to `4gb`, with `maxmemory-policy noeviction`.

#### Scenario: Bootstrap script cap matches deployment files
- **WHEN** `scripts/redis-bootstrap.sh` is inspected
- **THEN** its `--maxmemory` argument matches the value in `compose/kaine.yml`

#### Scenario: Native config uses the host variable
- **WHEN** the native Redis bootstrap writes `redis.conf` with `KAINE_REDIS_MAXMEMORY` unset
- **THEN** the file contains `maxmemory 4gb` and `maxmemory-policy noeviction`
- **AND** with `KAINE_REDIS_MAXMEMORY=12gb` the file contains `maxmemory 12gb`

#### Scenario: The native path reads compose/.env like compose does
- **WHEN** `compose/.env` holds the variable with leading spaces, an `export ` prefix, one pair of surrounding quotes or an unquoted ` # comment`
- **THEN** the native bootstrap uses the same value compose would, falls back to `4gb` for an empty value, and refuses a value that is not a Redis memory size
