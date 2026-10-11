## ADDED Requirements

### Requirement: A study configuration is applied last
The loader SHALL apply an optional study configuration `config/studies/<name>.toml`, selected by `KAINE_STUDY` (or an explicit argument), after the operator configuration, so a study's settings hold for the run whatever the operator's local file says. A selected study whose file is missing, whose name is not a slug, or which contains a `[modules]` table SHALL be refused with `ProfileError`. With no study selected the merged configuration SHALL be unchanged. The repository SHALL ship one study configuration per arm of the workspace-mediation test, `workspace_mediation_competitive`, `workspace_mediation_matched` and `workspace_mediation_pooled`, each setting `[lingua].temperature = 0.0` and its `[syneidesis].arm`.

#### Scenario: A study wins over the operator
- **WHEN** the operator file sets `[lingua].temperature = 0.9` and `KAINE_STUDY=workspace_mediation_pooled`
- **THEN** the merged configuration has temperature 0.0 and arm "pooled"

#### Scenario: A study may not change the module set
- **WHEN** the selected study file contains a `[modules]` table
- **THEN** loading raises `ProfileError`

#### Scenario: The module-addition study is not overridden by an ambient study
- **WHEN** the module-addition study runner starts a step while `KAINE_STUDY` is set in its environment
- **THEN** the step's child process runs without `KAINE_STUDY`
