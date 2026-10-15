## ADDED Requirements

### Requirement: The first-configuration profile decodes greedily
The `first_configuration` profile SHALL set the language organ's sampling temperature to 0, so that what the organ voices is a deterministic function of its input in the planned runs.

#### Scenario: Profile temperature
- **WHEN** the runtime configuration is resolved with the `first_configuration` profile
- **THEN** `[language].temperature` is 0.0
