# chronos-wetware-backend Specification

## Purpose
Chronos' recurrent network realised on a substrate territory, injected through the `chronos.network` seam with Chronos' events unchanged.

## Requirements

### Requirement: Chronos runs its forward model on the substrate

When `[backends].chronos = "cl1"`, Chronos' timing forward model SHALL be realised
on a substrate channel territory instead of the silicon CfC network, injected
behind Chronos' existing forward-model client interface. Chronos' `name`, bus
subscriptions, and `chronos.out` event shapes SHALL be unchanged.

#### Scenario: Backend selection preserves the event contract

- **WHEN** Chronos runs with `[backends].chronos = "cl1"`
- **THEN** its `chronos.out` events have the same schema as under the silicon CfC
- **AND** Chronos subscribes to and drives the cognitive cycle exactly as before

#### Scenario: Silicon remains the default

- **WHEN** `[backends].chronos` is absent or `"silicon"`
- **THEN** Chronos loads its upstream CfC network unchanged

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
