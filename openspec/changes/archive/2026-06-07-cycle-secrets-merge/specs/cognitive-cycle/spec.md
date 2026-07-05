## ADDED Requirements

### Requirement: Boot-time secrets merge for the cycle config

The cognitive cycle's boot-time configuration loader SHALL merge
`config/secrets.toml` into the configuration consumed by the module registry,
before `build_registry` runs. The Qdrant API key SHALL be resolved with the
precedence `KAINE_QDRANT_API_KEY` environment variable first, then
`config/secrets.toml` `[qdrant].api_key`, and the resolved value SHALL be
injected into the in-memory `[mnemos.qdrant].api_key` so the Mnemos factory
forwards it to the Qdrant client.

The loader SHALL NOT require the key to be present in the git-tracked
`config/kaine.toml`. When a key is already present at
`[mnemos.qdrant].api_key` in `config/kaine.toml`, the loader SHALL leave it
intact rather than overwrite it. When no key is resolvable from the environment
or `config/secrets.toml`, the loader SHALL NOT inject an empty value, so that
Mnemos surfaces its existing explicit error. If `config/secrets.toml` exists and
is group- or world-readable, the loader SHALL emit the same file-mode warning
the bus config loader emits.

#### Scenario: Key only in secrets.toml reaches Mnemos

- **WHEN** `config/secrets.toml` contains `[qdrant].api_key` and no
  `KAINE_QDRANT_API_KEY` env var is set and `config/kaine.toml` has no
  `[mnemos.qdrant].api_key`
- **THEN** the loaded cycle config has `mnemos.qdrant.api_key` equal to the
  secrets-file value
- **AND** a qdrant-backed Mnemos constructs without raising the missing-key
  error

#### Scenario: Environment variable takes precedence over secrets file

- **WHEN** both `KAINE_QDRANT_API_KEY` is set and `config/secrets.toml`
  `[qdrant].api_key` is present with a different value
- **THEN** the loaded cycle config has `mnemos.qdrant.api_key` equal to the
  environment-variable value

#### Scenario: Key absent everywhere yields a clear error, not a silent empty key

- **WHEN** neither `KAINE_QDRANT_API_KEY` nor `config/secrets.toml`
  `[qdrant].api_key` nor `config/kaine.toml` `[mnemos.qdrant].api_key` provides
  a key, and `mnemos` is enabled with `backend = "qdrant"`
- **THEN** no empty `api_key` is injected into the config
- **AND** Mnemos raises its explicit "requires qdrant_api_key" error

#### Scenario: Missing secrets file does not break boot

- **WHEN** `config/secrets.toml` does not exist but `KAINE_QDRANT_API_KEY` is
  set in the environment
- **THEN** the loader resolves the key from the environment without error
- **AND** the loaded cycle config has `mnemos.qdrant.api_key` equal to the
  environment-variable value
