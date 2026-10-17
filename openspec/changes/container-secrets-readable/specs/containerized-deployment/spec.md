## ADDED Requirements

### Requirement: Containers do not depend on a readable secrets file
Every reader of `config/secrets.toml` SHALL go through one loader. When the file exists but cannot be opened, the loader SHALL treat it as absent and log one warning per process that names the file by role. When the file is readable, its values SHALL be used exactly as before. The container deployments SHALL NOT mount `config/secrets.toml`, and every secret a container needs SHALL reach it through the environment. The file's mode and owner SHALL NOT be changed to make it readable.

#### Scenario: An unreadable file with the environment set
- **WHEN** `config/secrets.toml` exists with mode 0600 owned by another user, and `KAINE_REDIS_URL` and `KAINE_QDRANT_API_KEY` are set
- **THEN** the bus config and the Qdrant key resolve from the environment and one warning names the secrets file

#### Scenario: A readable file is unchanged
- **WHEN** `config/secrets.toml` is readable and the environment sets no secret
- **THEN** every secret resolves from the file as it does today

### Requirement: Caretaker tokens can come from the environment
The caretaker token loader SHALL read `KAINE_CARETAKER_TOKEN_<NAME>`, with `<NAME>` the channel's `token_name` upper-cased, before `[caretaker.tokens]` in `config/secrets.toml`.

#### Scenario: Token from the environment
- **WHEN** an HTTP channel names `token_name = "ntfy"` and `KAINE_CARETAKER_TOKEN_NTFY` is set
- **THEN** the notice is sent with that bearer token without reading the secrets file
