## ADDED Requirements

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
