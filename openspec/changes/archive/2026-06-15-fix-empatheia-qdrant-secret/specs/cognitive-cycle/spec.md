## MODIFIED Requirements

### Requirement: Boot-time secrets merge for the cycle config

The cognitive cycle's boot-time configuration loader SHALL merge
`config/secrets.toml` into the configuration consumed by the module registry,
before `build_registry` runs. The Qdrant API key SHALL be resolved with the
precedence `KAINE_QDRANT_API_KEY` environment variable first, then
`config/secrets.toml` `[qdrant].api_key`, and the resolved value SHALL be
injected into the in-memory `[qdrant].api_key` section of **every qdrant-backed
consumer** so each module's factory forwards it to the Qdrant client. The
qdrant-backed consumers are at minimum `[mnemos.qdrant]` and
`[empatheia.qdrant]`.

The loader SHALL NOT require the key to be present in the git-tracked
`config/kaine.toml`. For each consumer section, when a key is already present
(e.g. `[mnemos.qdrant].api_key` or `[empatheia.qdrant].api_key` in
`config/kaine.toml`), the loader SHALL leave that section's key intact rather
than overwrite it. When no key is resolvable from the environment or
`config/secrets.toml`, the loader SHALL NOT inject an empty value into any
consumer section, so that a qdrant-backed module surfaces its existing explicit
error. If `config/secrets.toml` exists and is group- or world-readable, the
loader SHALL emit the same file-mode warning the bus config loader emits.

#### Scenario: Key only in secrets.toml reaches Mnemos

- **WHEN** `config/secrets.toml` contains `[qdrant].api_key` and no
  `KAINE_QDRANT_API_KEY` env var is set and `config/kaine.toml` has no
  `[mnemos.qdrant].api_key`
- **THEN** the loaded cycle config has `mnemos.qdrant.api_key` equal to the
  secrets-file value
- **AND** a qdrant-backed Mnemos constructs without raising the missing-key
  error

#### Scenario: Key only in secrets.toml reaches Empatheia

- **WHEN** `config/secrets.toml` contains `[qdrant].api_key` and no
  `KAINE_QDRANT_API_KEY` env var is set and `config/kaine.toml` has no
  `[empatheia.qdrant].api_key`
- **THEN** the loaded cycle config has `empatheia.qdrant.api_key` equal to the
  secrets-file value
- **AND** a qdrant-backed Empatheia constructs without raising the missing-key
  error

#### Scenario: Environment variable takes precedence over secrets file

- **WHEN** both `KAINE_QDRANT_API_KEY` is set and `config/secrets.toml`
  `[qdrant].api_key` is present with a different value
- **THEN** the loaded cycle config has both `mnemos.qdrant.api_key` and
  `empatheia.qdrant.api_key` equal to the environment-variable value

#### Scenario: Explicit per-consumer key is left intact

- **WHEN** `config/kaine.toml` already sets `[empatheia.qdrant].api_key` to an
  explicit value and a different key is resolvable from the environment or
  `config/secrets.toml`
- **THEN** the loaded cycle config leaves `empatheia.qdrant.api_key` at its
  explicit value, unchanged

#### Scenario: Key absent everywhere yields a clear error, not a silent empty key

- **WHEN** neither `KAINE_QDRANT_API_KEY` nor `config/secrets.toml`
  `[qdrant].api_key` nor a per-consumer key in `config/kaine.toml` provides a
  key, and a qdrant-backed module (Mnemos or Empatheia) is enabled
- **THEN** no empty `api_key` is injected into that consumer's section
- **AND** the module raises its explicit "requires qdrant_api_key" error

#### Scenario: Missing secrets file does not break boot

- **WHEN** `config/secrets.toml` does not exist but `KAINE_QDRANT_API_KEY` is
  set in the environment
- **THEN** the loader resolves the key from the environment without error
- **AND** the loaded cycle config has `mnemos.qdrant.api_key` and
  `empatheia.qdrant.api_key` equal to the environment-variable value
