## ADDED Requirements

### Requirement: The base-thesis profile runs the temporal forward model
The base-thesis profile SHALL enable Chronos's forward-prediction head, so that a base-thesis run publishes a non-zero `temporal_prediction_error` once the head has a previous tick to predict from. The shipped `config/kaine.toml` SHALL keep the head disabled.

#### Scenario: Thesis profile
- **WHEN** the `thesis_test` profile is loaded
- **THEN** `[chronos].forward_prediction` is true

#### Scenario: Shipped default
- **WHEN** the shipped `config/kaine.toml` is loaded without a profile
- **THEN** `[chronos].forward_prediction` is false
