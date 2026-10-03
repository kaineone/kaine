# configuration-loading Specification

## Purpose
How KAINE builds and trusts its configuration: the shipped file, the module profile, the deployment tier and the operator overlay are merged in one order, the merged result's shape is validated, and the tools that act on it refuse to run on a configuration they could not find, read, parse or validate instead of silently falling back to defaults.

## Requirements

### Requirement: Merged configuration shape is validated
After merging the shipped configuration, the module profile, the deployment tier and the operator overlay, the loader SHALL validate the shape of the sections the runtime depends on and SHALL raise a configuration error naming the dotted key, the expected type and the actual type when any rule is violated. `[modules]` SHALL be a table whose values are booleans. `[tier]`, when present, SHALL be a table whose `name`, when present, is a string, whose `unsupported_modules`, when present, is a list of strings, and whose `oscillator_supported`, when present, is a boolean. `[oscillator]`, when present, SHALL be a table whose `enabled`, when present, is a boolean. `[security]` and `[deployment]`, when present, SHALL be tables. `[deployment].tier`, when present, SHALL be a string. `[security.state_encryption]`, when present, SHALL be a table whose `enabled`, when present, is a boolean. The error message SHALL NOT include the offending value. Sections and keys outside these rules SHALL pass through unchanged.

#### Scenario: A quoted boolean module toggle is rejected
- **WHEN** the operator overlay sets `[modules]` `soma = "false"`
- **THEN** loading raises a configuration error naming `modules.soma`, expecting a boolean and reporting a string, and no module is enabled by it

#### Scenario: A module table written as a list is rejected
- **WHEN** the merged configuration has `modules` as a list
- **THEN** loading raises a configuration error naming `modules` and expecting a table

#### Scenario: Shipped configuration passes
- **WHEN** the shipped `config/kaine.toml` is loaded with any shipped profile or tier file
- **THEN** validation passes

### Requirement: Runtime entrypoints load the operator overlay strictly
The loader used by the cognitive cycle and the pre-boot check SHALL raise a configuration error when the operator overlay file exists but cannot be read or parsed. Other callers MAY skip such a file and continue with the remaining layers, but SHALL log a warning naming the file and the parse error when they do. A command-line tool that acts on the configuration (the research submission CLI and the decommission CLI) SHALL load it with the same layering as the cycle (shipped, module profile, deployment tier, operator overlay, strict about the operator file) and SHALL NOT replace a configuration it failed to find, read, parse or validate with an empty configuration; it SHALL report "<tool>: configuration error: <message>" and exit with status 6, a status reserved for configuration errors. The pre-boot check SHALL report a configuration error as "pre-boot: configuration error: <message>" and exit with status 2, and the cycle SHALL refuse to boot with "kaine.cycle: configuration error: <message>" and a non-zero exit, both without a traceback.

#### Scenario: Unparsable operator file stops the runtime
- **WHEN** `config/kaine.operator.toml` contains a TOML syntax error and the pre-boot check or the cycle starts
- **THEN** it reports a configuration error naming the file and does not proceed on the shipped defaults

#### Scenario: Read-only surface warns and continues
- **WHEN** a read-only surface loads configuration while the operator file is unparsable
- **THEN** it continues with the other layers and a warning naming the file and the parse error is logged

#### Scenario: Research CLI refuses a malformed configuration
- **WHEN** the research submission CLI runs while the merged configuration fails validation
- **THEN** it reports a configuration error and exits non-zero instead of continuing with an empty configuration that drops the admissibility stream list and the encryption settings

#### Scenario: Missing configuration file stops a configuration-driven CLI
- **WHEN** the research submission CLI or the decommission CLI is run with a `--config` path that does not exist (for example from another working directory)
- **THEN** it reports a configuration error naming the path and exits with status 6 without doing anything else

### Requirement: The cycle boots the configuration its gates evaluated
The cognitive cycle entrypoint SHALL load its merged configuration once per boot. The boot-mode decisions (supervision mode, the unattended gate, the research safety net and the data root) and the boot itself SHALL use that same configuration. A profile selected with `--profile` SHALL therefore apply to the booted entity exactly as it applied to the gates, whether or not `KAINE_PROFILE` is set.

#### Scenario: A command-line profile reaches the booted entity
- **WHEN** the cycle is started with `--profile tier1` and `KAINE_PROFILE` is unset
- **THEN** the configuration the cycle boots is the one the gates evaluated, with the `tier1` profile applied, and not the default `thesis_test` profile

#### Scenario: Configuration is loaded once
- **WHEN** the cycle entrypoint boots
- **THEN** the configuration loader runs once, and the boot uses the configuration the gates evaluated

### Requirement: The cycle's log level comes from configuration
The cognitive cycle SHALL set its root log level from `[logging].level` after loading its configuration. Accepted values SHALL be `DEBUG`, `INFO`, `WARNING`, `ERROR` and `CRITICAL`, case-insensitive; when the key is absent the level SHALL be `INFO`. Any other value SHALL make the cycle refuse to boot with "kaine.cycle: configuration error: <message>" and a non-zero exit, without a traceback.

#### Scenario: A configured level is applied
- **WHEN** `[logging].level = "debug"`
- **THEN** the cycle's root logger level is DEBUG

#### Scenario: An unknown level refuses boot
- **WHEN** `[logging].level = "LOUD"`
- **THEN** the cycle exits non-zero with a configuration error naming the key and the accepted values
