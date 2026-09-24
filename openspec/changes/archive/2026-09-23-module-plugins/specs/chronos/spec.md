## ADDED Requirements

### Requirement: Chronos sizes its prediction head from its network
When forward prediction is enabled, Chronos SHALL size its forward-prediction head from the hidden width of the network it uses. For an injected network that width SHALL be the network's `units` attribute; for the default CfC network it SHALL remain `cfc_units`. An injected network without a `units` attribute SHALL cause a construction error when forward prediction is enabled.

#### Scenario: Injected network narrower than cfc_units
- **WHEN** Chronos is constructed with `forward_prediction = true`, `cfc_units = 32` and an injected network whose `units` is 12
- **THEN** the prediction head accepts the 12-wide hidden state and a workspace tick completes without a shape error

#### Scenario: Default network unchanged
- **WHEN** Chronos is constructed without an injected network
- **THEN** the prediction head is sized from `cfc_units` as before
