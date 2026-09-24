# redis-bootstrap Specification

## Purpose
Take KAINE's own authenticated Redis event bus from a fresh clone to a container that
answers PING in one command that is safe to repeat: the password is created once and
kept on re-runs (rotated only on request), recorded in `compose/.env` and the `[redis]`
table of `config/secrets.toml` without disturbing any other entry, and the memory cap
stays consistent across every deployment file.

## Requirements

### Requirement: Redis bootstrap documentation reflects the unified memory cap
`scripts/redis-bootstrap.sh` and any Redis deployment documentation SHALL use the same `--maxmemory` value as `compose/kaine.yml` and `quadlet/kaine-redis.container`.

#### Scenario: Bootstrap script cap matches deployment files
- **WHEN** `scripts/redis-bootstrap.sh` is inspected
- **THEN** its `--maxmemory` argument matches the value in `compose/kaine.yml`

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
