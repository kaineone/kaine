## ADDED Requirements

### Requirement: Operator config-override layer
The system SHALL provide a shared `load_kaine_config()` that loads the shipped `config/kaine.toml`
and deep-merges an optional, gitignored `config/kaine.operator.toml` over it, with operator values
taking precedence (recursive merge of nested tables). The cycle entrypoint and the Nexus config
readers SHALL use this loader so operator overrides apply uniformly. The shipped `config/kaine.toml`
SHALL remain unchanged (all modules disabled); operator choices live only in the override file.

#### Scenario: Operator override wins
- **WHEN** `config/kaine.operator.toml` sets `[modules].soma = true` over a shipped `false`
- **THEN** `load_kaine_config()` returns `soma = true` while the shipped `config/kaine.toml` on disk
  is unchanged

#### Scenario: No override file is harmless
- **WHEN** `config/kaine.operator.toml` does not exist
- **THEN** `load_kaine_config()` returns the shipped configuration unchanged

#### Scenario: Nested tables merge, not replace
- **WHEN** the override sets one key inside a table that the shipped config also populates
- **THEN** the merged table contains the override's key plus the shipped table's other keys

### Requirement: Guided first-run wizard
The system SHALL provide a first-run wizard (`python -m kaine.setup`) that guides an operator through
configuration and writes only to `config/kaine.operator.toml`. It SHALL require an explicit typed
acknowledgement of the CAL Article 4 welfare obligations before configuring an entity; scan the host
via `describe_host()` and propose device assignments; let the operator select modules and record the
served model, voice, and STT identifiers; offer to install the optional extras implied by the chosen
modules on explicit confirmation; offer opt-in research-metrics submission; and print a summary with
the required environment gates and launch steps. The wizard SHALL NOT boot the entity and SHALL
support a non-interactive mode for testing.

#### Scenario: Welfare acknowledgement is required
- **WHEN** the operator does not give the CAL welfare acknowledgement
- **THEN** the wizard does not write an entity configuration

#### Scenario: Choices persist to the override file only
- **WHEN** the operator completes the wizard
- **THEN** the selections are written to `config/kaine.operator.toml` and `config/kaine.toml` is not
  modified

#### Scenario: Hardware scan proposes devices
- **WHEN** the host reports multiple GPUs
- **THEN** the wizard proposes a primary/secondary device assignment, falling back gracefully on a
  single-GPU or CPU-only host

#### Scenario: Metrics submission is opt-in
- **WHEN** the operator declines research participation
- **THEN** the wizard leaves `[research_submission].enabled` false

#### Scenario: The wizard never boots the entity
- **WHEN** the wizard finishes
- **THEN** no cognitive cycle is started; only configuration is written
