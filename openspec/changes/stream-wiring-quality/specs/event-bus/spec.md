## ADDED Requirements

### Requirement: Canonical stream-name helper is the single source of truth
`kaine.bus.schema.module_stream()` SHALL be the authoritative source for mapping a module name to its output stream, and consumers SHALL use it instead of string concatenation or literals.

#### Scenario: New consumer uses the helper
- **WHEN** a new module consumer is added
- **THEN** it imports `module_stream` from `kaine.bus.schema`

#### Scenario: Config stream keys are validated against canonical names
- **WHEN** `config/kaine.toml` contains a `[bus.per_stream_maxlen]` key
- **THEN** boot validation confirms the key matches a known canonical stream name or logs a warning
