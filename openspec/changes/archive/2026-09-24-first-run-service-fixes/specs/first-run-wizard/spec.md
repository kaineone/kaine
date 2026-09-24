## ADDED Requirements

### Requirement: Setup provides the Nexus operator token
When no Nexus operator token is configured, `python -m kaine.setup` SHALL
generate one of at least 32 characters with a cryptographically secure
generator. It SHALL store the token as `operator_token` in the `[nexus]` table
of `config/secrets.toml`, mode 600, preserving the rest of the file. It SHALL
NOT replace a token that is already configured, and SHALL NOT print the token.

#### Scenario: A fresh install gets a token
- **WHEN** setup runs, `config/secrets.toml` has no `[nexus].operator_token`, and `KAINE_NEXUS_TOKEN` is unset
- **THEN** the file afterwards holds an `operator_token` of at least 32 characters
- **AND** setup's output states where the token is stored without showing it

#### Scenario: An existing token is kept
- **WHEN** setup runs, and either `config/secrets.toml` already holds `[nexus].operator_token` or `KAINE_NEXUS_TOKEN` is set
- **THEN** `config/secrets.toml`'s token value is unchanged
- **AND** no token is written

### Requirement: Dependency probes use the configured service ports
The wizard's dependency detection SHALL probe each KAINE-owned service on the
port KAINE is configured to use, never on the upstream default of another
installation:

- Redis: `[redis].port`.
- Qdrant: `[mnemos.qdrant].port`, then `[empatheia.qdrant].port`, then 6533.

Containerised services SHALL NOT be reported as installed or missing according
to a host binary on `PATH`.

#### Scenario: Qdrant is probed on KAINE's port
- **WHEN** no Qdrant port is configured
- **THEN** detection probes 127.0.0.1:6533, not 6333

#### Scenario: A configured Qdrant port is honoured
- **WHEN** `[mnemos.qdrant].port` is 7000
- **THEN** detection probes 127.0.0.1:7000
