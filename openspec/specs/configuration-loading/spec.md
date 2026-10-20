# configuration-loading Specification

## Purpose
How KAINE builds and trusts its configuration: the shipped file, the module profile, the deployment tier and the operator overlay are merged in one order, the merged result's shape is validated, and the tools that act on it refuse to run on a configuration they could not find, read, parse or validate instead of silently falling back to defaults.

## Requirements

### Requirement: Merged configuration shape is validated
After merging the shipped configuration, the module profile, the deployment tier and the operator overlay, the loader SHALL validate the shape of the sections the runtime depends on and SHALL raise a configuration error naming the dotted key, the expected type and the actual type when any rule is violated. `[modules]` SHALL be a table whose values are booleans. `[tier]`, when present, SHALL be a table whose `name`, when present, is a string, whose `unsupported_modules`, when present, is a list of strings, and whose `oscillator_supported`, when present, is a boolean. `[oscillator]`, when present, SHALL be a table whose `enabled`, when present, is a boolean. `[security]` and `[deployment]`, when present, SHALL be tables. `[deployment].tier`, when present, SHALL be a string. `[security.state_encryption]`, when present, SHALL be a table whose `enabled`, when present, is a boolean. The error message SHALL NOT include the offending value. Sections and keys outside these rules SHALL pass through unchanged.

#### Scenario: A quoted boolean module toggle is rejected
- **WHEN** the operator overlay sets `[modules]` `interoception = "false"`
- **THEN** loading raises a configuration error naming `modules.interoception`, expecting a boolean and reporting a string, and no module is enabled by it

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
- **THEN** the configuration the cycle boots is the one the gates evaluated, with the `tier1` profile applied, and not the default `first_configuration` profile

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

### Requirement: Organ, key and disk defaults have one source
The organ chat URL default, the model-server API key lookup and the free-disk floor SHALL be defined once, in `kaine/defaults.py`, and every consumer SHALL read them from there. The key lookup SHALL prefer `[language].api_key` and fall back to the `KAINE_MODEL_SERVER_API_KEY` environment variable. A missing key SHALL read as None, never as an empty string that a client might send.

#### Scenario: A configured key wins over the environment
- **WHEN** `[language].api_key` is set and `KAINE_MODEL_SERVER_API_KEY` is also set
- **THEN** `model_server_api_key(config)` returns the configured key

#### Scenario: The environment fills a missing key
- **WHEN** `[language].api_key` is absent or empty and `KAINE_MODEL_SERVER_API_KEY` is set
- **THEN** `model_server_api_key(config)` returns the environment value

#### Scenario: No stray copies of the organ port
- **WHEN** the source tree under `kaine/` is scanned
- **THEN** the literal `11434` appears only in `kaine/net.py` and `kaine/defaults.py`

### Requirement: Social cognition operator sources are checked when the config loads
Config loading SHALL refuse a `[social_cognition].operator_sources` that is not a list of strings, naming the key, before the boot opens any resource.

#### Scenario: A string instead of a list
- **WHEN** `[social_cognition].operator_sources` is the string `"live_mic"`
- **THEN** loading the config fails with a shape error naming `social_cognition.operator_sources`

### Requirement: Each configuration layer is normalized from old names
Before merging, the loader SHALL rewrite each layer (shipped file, module
profile, deployment tier, operator overlay, study) from old table names, key
names and listed values to their new names, using `kaine/legacy_names.py`.
A layer that used any old name SHALL log exactly one warning line naming the
file, each old name with its new name, and the last release that reads them.
A layer that sets both the old and the new name for the same table or key SHALL
fail to load with a configuration error naming both. The study table
allowlist, the shape validation and the unknown-key guard SHALL run on the
normalized names.

#### Scenario: An operator overlay with old tables loads
- **WHEN** the operator overlay sets `[thymos]`, `[modules].thymos = true`,
  `[perception_feed.womb]` and `[perception_feed].mode = "womb"`
- **THEN** the merged configuration has `[affect]`, `[modules].affect = true`,
  `[perception_feed.stimulus_source]` and `mode = "stimulus_source"`, and the
  loader logs one warning line for that file

#### Scenario: Old and new names in one layer are refused
- **WHEN** one layer sets both `[spot]` and `[supervisor]`
- **THEN** loading fails with a configuration error naming both tables

#### Scenario: A study with an old table passes the allowlist
- **WHEN** a study sets `[syneidesis]`
- **THEN** it is accepted as `[workspace]` and the allowlist check passes

### Requirement: A study configuration is applied last
The loader SHALL apply an optional study configuration `config/studies/<name>.toml`, selected by `KAINE_STUDY` (or an explicit argument), after the operator configuration, so a study's settings hold for the run whatever the operator's local file says. A selected study whose file is missing or whose name is not a slug SHALL be refused with `ProfileError`, and a study file SHALL set only the `[language]`, `[workspace]`, `[experiment]` and `[individuation]` tables; any other table SHALL be refused with `ProfileError`. The run context and the run manifest SHALL record the study's name in `study` (null when none is selected). With no study selected the merged configuration SHALL be unchanged. The repository SHALL ship one study configuration per arm of the workspace-mediation test, `workspace_mediation_competitive`, `workspace_mediation_matched` and `workspace_mediation_pooled`, each setting `[language].temperature = 0.0` and its `[workspace].arm`.

#### Scenario: A study wins over the operator
- **WHEN** the operator file sets `[language].temperature = 0.9` and `KAINE_STUDY=workspace_mediation_pooled`
- **THEN** the merged configuration has temperature 0.0 and arm "pooled"

#### Scenario: A study may set only its allowed tables
- **WHEN** the selected study file contains a `[modules]`, `[preservation]` or `[oscillator]` table
- **THEN** loading raises `ProfileError`

#### Scenario: The manifest names the study
- **WHEN** a run starts with `KAINE_STUDY=workspace_mediation_matched`
- **THEN** its run manifest has `study` "workspace_mediation_matched"

#### Scenario: The module-addition study is not overridden by an ambient study
- **WHEN** the module-addition study runner starts a step while `KAINE_STUDY` is set in its environment
- **THEN** the step's child process runs without `KAINE_STUDY`

### Requirement: Studies may set the tone rule
A study configuration SHALL be allowed to set `[audition].tone_rule` and no other `[audition]` key; any other key in a study's `[audition]` table SHALL raise `ProfileError`. The repository SHALL ship `workspace_mediation_pilot_tone` (role pilot) and `workspace_mediation_tone` (role test), which run the on arm with `tone_rule = "error_ratio"`. The boot gate SHALL refuse a workspace-mediation study whose tone rule is not `error_ratio` for the two tone studies or not `categorical` for every other study.

#### Scenario: A study sets another Audition key
- **WHEN** a study file sets `[audition].alert_salience`
- **THEN** loading the configuration raises `ProfileError`

#### Scenario: An arm run with the variant's rule
- **WHEN** the operator config sets `tone_rule = "error_ratio"` and the study is `workspace_mediation_competitive`
- **THEN** the boot gate refuses the run

### Requirement: The old module profile name resolves as a deprecated alias
The module profile that defines the first configuration SHALL be named `first_configuration`, and the runtime loader SHALL apply it when no profile is selected. The name `thesis_test`, given as `--profile`, as `KAINE_PROFILE` or as the `profile` argument of the config loader, SHALL resolve to `first_configuration` and SHALL log one warning that names the replacement and the last release that reads the old name (`ALIAS_LAST_RELEASE`). No file named `thesis_test.toml` SHALL ship.

#### Scenario: A pinned old profile name
- **WHEN** the cycle starts with `KAINE_PROFILE=thesis_test`
- **THEN** the `first_configuration` profile is applied, the merged configuration equals the one `KAINE_PROFILE=first_configuration` produces, and one deprecation warning naming `first_configuration` is logged

#### Scenario: No profile selected
- **WHEN** the runtime configuration is loaded with no `--profile` and no `KAINE_PROFILE`
- **THEN** the `first_configuration` profile is applied
