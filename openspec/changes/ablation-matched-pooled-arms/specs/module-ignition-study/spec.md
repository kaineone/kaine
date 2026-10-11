## ADDED Requirements

### Requirement: Study steps decode greedily in the competitive arm
Every study step's overlay SHALL set `[lingua].temperature` to 0.0 and `[syneidesis].arm` to `"competitive"`, overriding the operator configuration.

#### Scenario: An operator temperature does not reach a study step
- **WHEN** the operator configuration sets `[lingua].temperature = 0.7` and `[syneidesis].arm = "pooled"`
- **THEN** the step's overlay has temperature 0.0 and arm "competitive"
