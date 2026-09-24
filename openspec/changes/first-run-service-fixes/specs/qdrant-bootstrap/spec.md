## ADDED Requirements

### Requirement: Qdrant bootstrap is a re-runnable setup path
`scripts/qdrant-bootstrap.sh` SHALL reuse the existing usable
`KAINE_QDRANT_API_KEY` from `compose/.env`, or generate a new random key when
none exists or when `--rotate` is given. It SHALL upsert exactly one
`KAINE_QDRANT_API_KEY=` line into `compose/.env`, preserving every other line,
and SHALL mirror the key into the `api_key` field of the `[qdrant]` table of
`config/secrets.toml` without touching any other table. `--keep-key` SHALL
remain accepted and SHALL behave exactly as a run with no flags.

#### Scenario: Re-running keeps the key by default
- **WHEN** the script is run again with no flags
- **THEN** `compose/.env` and `config/secrets.toml` hold the same key as before

#### Scenario: --rotate replaces the key
- **WHEN** the script is run with `--rotate`
- **THEN** a new key is written to both files
- **AND** the container is recreated to use it

#### Scenario: The Redis password survives
- **WHEN** `compose/.env` holds `KAINE_REDIS_PASSWORD=`
- **AND** the script runs
- **THEN** that line is unchanged
