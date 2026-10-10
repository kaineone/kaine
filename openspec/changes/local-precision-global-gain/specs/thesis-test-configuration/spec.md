## ADDED Requirements

### Requirement: The base-thesis profile decodes greedily
The `thesis_test` profile SHALL set the language organ's sampling temperature to 0, so that what the organ voices is a deterministic function of its input in the planned runs.

#### Scenario: Profile temperature
- **WHEN** the runtime configuration is resolved with the `thesis_test` profile
- **THEN** `[lingua].temperature` is 0.0
