## ADDED Requirements

### Requirement: The old module profile name resolves as a deprecated alias
The module profile that defines the first configuration SHALL be named `first_configuration`, and the runtime loader SHALL apply it when no profile is selected. The name `thesis_test`, given as `--profile`, as `KAINE_PROFILE` or as the `profile` argument of the config loader, SHALL resolve to `first_configuration` and SHALL log one warning that names the replacement and the last release that reads the old name (`ALIAS_LAST_RELEASE`). No file named `thesis_test.toml` SHALL ship.

#### Scenario: A pinned old profile name
- **WHEN** the cycle starts with `KAINE_PROFILE=thesis_test`
- **THEN** the `first_configuration` profile is applied, the merged configuration equals the one `KAINE_PROFILE=first_configuration` produces, and one deprecation warning naming `first_configuration` is logged

#### Scenario: No profile selected
- **WHEN** the runtime configuration is loaded with no `--profile` and no `KAINE_PROFILE`
- **THEN** the `first_configuration` profile is applied
