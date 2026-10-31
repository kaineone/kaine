## ADDED Requirements

### Requirement: The self-model predicts the entity's own next state
With `[self_model.self_prediction].enabled = true`, at each broadcast the self-model module SHALL predict the next self-state vector (affect dimensions, the four drives, the leading source class, its own last intent kind, fatigue) with a frozen reservoir and an online linear readout, taking one squared-error gradient step except during sleep. `enabled` SHALL ship `false`, and with it off the module SHALL behave as today.

#### Scenario: Shipped configuration
- **WHEN** the self-model module runs with the shipped configuration
- **THEN** no self-prediction is made and the module's events are those of today's build

#### Scenario: Sleep
- **WHEN** a broadcast arrives during sleep
- **THEN** the readout's weights do not change

### Requirement: A self-prediction error competes only when enabled to
The module SHALL keep the self-prediction error's running mean and, with `compete = true`, SHALL publish `self_model.surprise` carrying the error ratio and the self-state components with the largest errors, by name only, at the intensity `graded_intensity(baseline, alert, ratio)`. With `compete = false` it SHALL record the error statistics and publish no `self_model.surprise`. When accessed, the organ's turn SHALL receive a phrase stating only that the entity did not expect its own state.

#### Scenario: Recording only
- **WHEN** `compete = false` and the self-prediction error ratio is 3
- **THEN** no `self_model.surprise` event is published and the error is recorded

#### Scenario: Competing
- **WHEN** `compete = true` and the error ratio is 3
- **THEN** a `self_model.surprise` event is published at the intensity for ratio 3 with no number in its felt rendering

### Requirement: The agency estimate is recorded and drives nothing
For each of the entity's own intents and acts, the module SHALL record per intent kind the share of the observed change in the drive and source components that the intent explains under the self-prediction readout, and SHALL NOT pass the estimate to the credit rule, the welfare indicators, the action layer or the organ.

#### Scenario: An intent explains nothing
- **WHEN** the observed change equals the change predicted without the intent
- **THEN** the recorded share for that intent is zero

### Requirement: The attention schema's accuracy is recorded
When the sequence module publishes its predicted next broadcast, the self-model SHALL record per broadcast whether the prediction's highest-weighted source block matches the next accessed leading source, and SHALL give the running accuracy per viewing in the content-free research log.

#### Scenario: A correct forecast
- **WHEN** the sequence prediction's highest-weighted source is vision and the next accessed leading member is from vision
- **THEN** the record counts a correct forecast

### Requirement: The self-prediction model is part of the entity and is never corrective
The readout weights, error statistics and records SHALL be serialized with the self-model state, encrypted when state encryption is on, restored on revive and copied into a fork. No control path SHALL read the self-prediction error to move the entity's state toward its prediction.

#### Scenario: Fork
- **WHEN** a branch is made from a preserved entity
- **THEN** its self-prediction readout starts as a copy of the parent's
