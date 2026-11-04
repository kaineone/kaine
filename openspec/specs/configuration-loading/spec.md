## ADDED Requirements

### Requirement: Shipped study files enable the module supervisor
Every study file under `config/studies/` SHALL set `[supervisor].enabled = true`, so a research run selected through `KAINE_STUDY` passes the research gate's supervisor condition whatever the operator config says. A test SHALL read every shipped study file and fail when one does not set it. The shipped `config/kaine.toml` SHALL keep `[supervisor].enabled = false`.

#### Scenario: A new study file without the supervisor
- **WHEN** a study file is added under `config/studies/` without `[supervisor].enabled = true`
- **THEN** the test fails and names the file
