# sequence-predictive Specification

## Purpose
The sequence module's predictive timing capability runs a CfC forward model over temporal features, publishes `temporal_prediction_error` on `sequence.report`, and uses that error to drive anomaly salience instead of a rolling z-score on hidden-state norm.

## Requirements

### Requirement: Temporal forward model drives anomaly salience
The sequence module SHALL use its CfC to predict the next temporal feature vector and SHALL
publish a `temporal_prediction_error` on `sequence.report`, driving anomaly
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
- **WHEN** the sequence module publishes a report
- **THEN** the payload still contains `anomaly_score`, `habituation_score`, and
  `rumination_detected`

### Requirement: The first-configuration profile runs the temporal forward model
The first-configuration profile SHALL enable the sequence module's forward-prediction head, so that a first-configuration run publishes a non-zero `temporal_prediction_error` once the head has a previous tick to predict from. The shipped `config/kaine.toml` SHALL keep the head disabled.

#### Scenario: First-configuration profile
- **WHEN** the `first_configuration` profile is loaded
- **THEN** `[sequence].forward_prediction` is true

#### Scenario: Shipped default
- **WHEN** the shipped `config/kaine.toml` is loaded without a profile
- **THEN** `[sequence].forward_prediction` is false

### Requirement: Sequence's reservoir receives the elapsed time
The sequence module SHALL advance its continuous-time reservoir on each broadcast with a timespan equal to the subjective seconds since the previous broadcast divided by the mean of that interval over the last 32 broadcasts (current included), clipped to `[0, 10]` and equal to 1.0 on the first broadcast. A temporal network supplied by a plugin SHALL receive a timespan only if it declares that it accepts one.

#### Scenario: A gap in broadcasts lengthens the timespan
- **WHEN** a broadcast arrives after a gap four times the recent mean interval
- **THEN** that reservoir step uses a timespan above 1.0

### Requirement: A long pause does not distort later reservoir steps
Before an interval between broadcasts enters the window that sets the mean interval, the sequence module SHALL clip it to ten times the mean of the intervals already in the window. The step that follows the pause SHALL still use the raw interval over the window mean, capped at 10.

#### Scenario: Normal steps resume after a pause
- **WHEN** broadcasts arrive 0.2 s apart, then one arrives after a 600 s pause, then they resume 0.2 s apart
- **THEN** the step after the pause has a timespan of 10, and the next normal step's timespan is between 0.5 and 1.5
