# sequence-wetware-backend Specification

## Purpose
The sequence module's recurrent network realised on a substrate territory, injected through the `sequence.network` seam with the sequence module's events unchanged.

## Requirements

### Requirement: Sequence runs its forward model on the substrate

When `[backends].sequence = "cl1"`, the sequence module's timing forward model SHALL be realised
on a substrate channel territory instead of the silicon CfC network, injected
behind the sequence module's existing forward-model client interface. The sequence module's `name`, bus
subscriptions, and `sequence.out` event shapes SHALL be unchanged.

#### Scenario: Backend selection preserves the event contract

- **WHEN** the sequence module runs with `[backends].sequence = "cl1"`
- **THEN** its `sequence.out` events have the same schema as under the silicon CfC
- **AND** the sequence module subscribes to and drives the cognitive cycle exactly as before

#### Scenario: Silicon remains the default

- **WHEN** `[backends].sequence` is absent or `"silicon"`
- **THEN** the sequence module loads its upstream CfC network unchanged

### Requirement: Timing prediction error reflects temporal structure

The wetware backend SHALL encode recent workspace-temporal context as a stim
pattern and decode the response into a next-interval prediction and a
prediction-error salience. On temporally structured input the prediction error
SHALL be lower than on the same input temporally scrambled, demonstrating the
biological forward model does predictive work.

#### Scenario: Structured vs scrambled stimulus

- **WHEN** the backend receives a temporally structured stimulus and, separately,
  a scrambled version of it
- **THEN** the prediction-error salience is measurably lower for the structured
  stimulus than for the scrambled one
