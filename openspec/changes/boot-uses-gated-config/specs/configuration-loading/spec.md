## ADDED Requirements

### Requirement: The cycle boots the configuration its gates evaluated
The cognitive cycle entrypoint SHALL load its merged configuration once per boot. The boot-mode decisions (supervision mode, the unattended gate, the research safety net and the data root) and the boot itself SHALL use that same configuration. A profile selected with `--profile` SHALL therefore apply to the booted entity exactly as it applied to the gates, whether or not `KAINE_PROFILE` is set.

#### Scenario: A command-line profile reaches the booted entity
- **WHEN** the cycle is started with `--profile tier1` and `KAINE_PROFILE` is unset
- **THEN** the configuration the cycle boots is the one the gates evaluated, with the `tier1` profile applied, and not the default `thesis_test` profile

#### Scenario: Configuration is loaded once
- **WHEN** the cycle entrypoint boots
- **THEN** the configuration loader runs once, and the boot uses the configuration the gates evaluated
