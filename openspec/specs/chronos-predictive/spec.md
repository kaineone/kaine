# chronos-predictive Specification

## Purpose
Chronos's predictive timing capability runs a CfC forward model over temporal features, publishes `temporal_prediction_error` on `chronos.report`, and uses that error to drive anomaly salience instead of a rolling z-score on hidden-state norm.

## Requirements

### Requirement: Temporal forward model drives anomaly salience
Chronos SHALL use its CfC to predict the next temporal feature vector and SHALL
publish a `temporal_prediction_error` on `chronos.report`, driving anomaly
salience from that error rather than from the rolling z-score of the hidden-state
norm. The CfC SHALL adapt online and suspend adaptation during offline
maintenance. The legacy `anomaly_score`, `habituation_score`, and
`rumination_detected` fields SHALL remain on the payload.

#### Scenario: Regular cadence yields low salience
- **WHEN** events arrive on a steady, predictable cadence the model has adapted to
- **THEN** the temporal prediction error and resulting anomaly salience are low

#### Scenario: Timing surprise yields high salience
- **WHEN** an event arrives at a time the forward model did not predict
- **THEN** the `temporal_prediction_error` rises and the event's salience
  increases

#### Scenario: Diagnostics fields retained
- **WHEN** Chronos publishes a report
- **THEN** the payload still contains `anomaly_score`, `habituation_score`, and
  `rumination_detected`

### Requirement: The base-thesis profile runs the temporal forward model
The base-thesis profile SHALL enable Chronos's forward-prediction head, so that a base-thesis run publishes a non-zero `temporal_prediction_error` once the head has a previous tick to predict from. The shipped `config/kaine.toml` SHALL keep the head disabled.

#### Scenario: Thesis profile
- **WHEN** the `thesis_test` profile is loaded
- **THEN** `[chronos].forward_prediction` is true

#### Scenario: Shipped default
- **WHEN** the shipped `config/kaine.toml` is loaded without a profile
- **THEN** `[chronos].forward_prediction` is false
