# soma-wetware-backend Specification

## Purpose
Soma's interoceptive forward model with the substrate in place of its frozen reservoir and a silicon readout, so prediction error keeps its usual units.

## Requirements

### Requirement: Soma runs its interoceptive forward model on the substrate
When the plugin configuration sets `soma = "cl1"` and gives Soma a channel territory, kaine SHALL construct stock Soma with a `WetwareInteroceptiveModel` injected through the `soma.forward_model` seam. Soma's name, bus subscriptions and `soma.out` event shapes SHALL be unchanged. Silicon SHALL remain the default when the key is absent or `"silicon"`.

#### Scenario: Event contract preserved
- **WHEN** Soma runs with `soma = "cl1"`
- **THEN** its `soma.out` events have the same types and payload keys as under the silicon model

### Requirement: Prediction error keeps the silicon semantics
Each `step(feature)` SHALL return the L2 distance between `feature` and the prediction made on the previous step (0.0 on the first step), SHALL return 0.0 and skip the step for a non-finite feature, and SHALL raise `ValueError` for a feature of the wrong length. `prediction_error_to_salience` SHALL compute the same mapping as the silicon model.

#### Scenario: Load excursion raises surprise
- **WHEN** a steady feature vector is followed by one whose CPU component jumps from 0.2 to 0.9
- **THEN** the error returned for the jump is larger than every error returned during the steady phase after the first few steps

### Requirement: Adaptation suspends during offline cycles
While `suspended` is true the model SHALL NOT change its readout weights and `adaptation_steps` SHALL NOT advance; after `suspended` returns to false, adaptation SHALL resume.

#### Scenario: Hypnos suspends adaptation
- **WHEN** `suspended` is set true for five steps and then false for five steps
- **THEN** the readout weights and `adaptation_steps` are unchanged across the suspended steps and advance afterwards

### Requirement: Snapshots are shape-checked
`state_dict()` SHALL return the readout weights, and `load_state_dict` SHALL restore them, raising `ValueError` when the shapes do not match this model.

#### Scenario: Silicon snapshot rejected
- **WHEN** `load_state_dict` receives weights shaped for a 32-unit silicon readout and the model has 12 units
- **THEN** it raises `ValueError` and keeps its current weights
