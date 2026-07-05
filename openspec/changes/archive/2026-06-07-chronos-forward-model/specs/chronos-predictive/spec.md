## ADDED Requirements

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
