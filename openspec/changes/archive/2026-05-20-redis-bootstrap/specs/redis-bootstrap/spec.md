## ADDED Requirements

### Requirement: Redis bootstrap script is the canonical setup path
The repository SHALL ship `scripts/redis-bootstrap.sh` that brings the
KAINE Redis bus from a fresh clone to a healthy, authenticated,
ping-able state in one invocation. The script SHALL generate (or
reuse with `--keep-password`) a strong random password, write
`compose/.env` from scratch with exactly one `KAINE_REDIS_PASSWORD=`
line, mirror that password into `config/secrets.toml`'s
`[redis].password`, recreate the container via
`docker compose -f compose/redis.yml down && up -d`, and confirm
the bus answers `PING` with `PONG`.

#### Scenario: Fresh clone reaches PONG in one command
- **WHEN** an operator on a fresh clone runs `bash scripts/redis-bootstrap.sh`
- **THEN** the container is healthy, `config/secrets.toml`'s
  `[redis].password` matches `compose/.env`'s `KAINE_REDIS_PASSWORD`,
  and `redis-cli -h 127.0.0.1 -p 6479 -a $PW ping` returns `PONG`

#### Scenario: Re-running rotates the password by default
- **WHEN** the script is run a second time without `--keep-password`
- **THEN** a new random password is generated, written, mirrored, and
  the container is recreated to use it

#### Scenario: --keep-password preserves the existing password
- **WHEN** the script is run with `--keep-password` and
  `compose/.env` already contains a `KAINE_REDIS_PASSWORD=` value
- **THEN** that value is preserved in both `compose/.env` and
  `config/secrets.toml` and the container is restarted in place

#### Scenario: compose/.env.example does not trip a duplicate-key trap
- **WHEN** an operator follows the manual SETUP.md steps and copies
  `compose/.env.example` to `compose/.env` before appending a real
  password line
- **THEN** the resulting file has exactly one active
  `KAINE_REDIS_PASSWORD=` line because the example's placeholder is
  commented out
