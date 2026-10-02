# redis-bootstrap Specification

## Purpose
Take KAINE's own authenticated Redis event bus from a fresh clone to a container that
answers PING in one command that is safe to repeat: the password is created once and
kept on re-runs (rotated only on request), recorded in `compose/.env` and the `[redis]`
table of `config/secrets.toml` without disturbing any other entry, and the memory cap
stays consistent across every deployment file.

## Requirements

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

### Requirement: Redis bootstrap is a re-runnable canonical setup path
`scripts/redis-bootstrap.sh` SHALL take a fresh clone to a running, authenticated,
ping-able state in one invocation. The script SHALL reuse the existing usable
password in `compose/.env`, or generate a strong random password when none
exists or when `--rotate` is given. It SHALL upsert exactly one
`KAINE_REDIS_PASSWORD=` line into `compose/.env` while preserving every other
line of that file, and mirror the password into the `password` field of the
`[redis]` table of `config/secrets.toml` without touching any other table. It
SHALL recreate the container via
`docker compose -f compose/redis.yml down && up -d`, and confirm that the bus
answers `PING` with `PONG`.

#### Scenario: Fresh clone reaches PONG in one command
- **WHEN** an operator on a fresh clone runs `bash scripts/redis-bootstrap.sh`
- **THEN** the container is healthy
- **AND** `config/secrets.toml`'s `[redis].password` matches `compose/.env`'s `KAINE_REDIS_PASSWORD`
- **AND** `redis-cli -h 127.0.0.1 -p 6479 -a $PW ping` returns `PONG`

#### Scenario: Re-running keeps the password by default
- **WHEN** the script is run a second time with no flags
- **AND** `compose/.env` already holds a usable `KAINE_REDIS_PASSWORD=` value
- **THEN** that value is preserved in both `compose/.env` and `config/secrets.toml`
- **AND** the container is restarted in place

#### Scenario: --rotate replaces the password
- **WHEN** the script is run with `--rotate`
- **THEN** a new random password is generated, written and mirrored
- **AND** the container is recreated to use it

#### Scenario: --keep-password remains accepted
- **WHEN** the script is run with `--keep-password`
- **THEN** it behaves exactly as a run with no flags

#### Scenario: Other compose settings survive a re-run
- **WHEN** `compose/.env` holds `KAINE_QDRANT_API_KEY=` or any other line
- **AND** the script runs
- **THEN** every such line is unchanged afterwards

#### Scenario: Only the redis table is edited
- **WHEN** `config/secrets.toml` contains a `password` field in a table other than `[redis]`
- **THEN** the script leaves that field unchanged

#### Scenario: compose/.env.example does not trip a duplicate-key trap
- **WHEN** an operator follows the manual SETUP.md steps
- **AND** they copy `compose/.env.example` to `compose/.env` before appending a real password line
- **THEN** the resulting file has exactly one active `KAINE_REDIS_PASSWORD=` line, because the example's placeholder is commented out

### Requirement: The bus and memory store run without containers
The Redis and Qdrant bootstraps SHALL offer a native path that needs no container runtime and no root: a user-level server per service, bound to loopback on the KAINE ports, authenticated with the same generated secret the container path uses, persisting under the entity's state directory, and supervised by `systemd --user` when available or as a supervised background process otherwise. A downloaded server binary SHALL be pinned by version and sha256 and refused on mismatch. Without an explicit choice, the bootstraps SHALL use containers when a container runtime is present and the native path otherwise.

#### Scenario: A host without Docker
- **WHEN** the Redis bootstrap runs on a host with no container runtime
- **THEN** a user-level redis-server starts on 127.0.0.1:6479 with the generated password, and the bus answers PONG

#### Scenario: A tampered download
- **WHEN** the Qdrant binary's sha256 does not match the pinned value
- **THEN** the bootstrap stops without starting it
