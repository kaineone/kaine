## ADDED Requirements

### Requirement: Nous can run active inference on the substrate

When `[backends].nous = "cl1"`, Nous' generative-model client SHALL be realised on
a substrate territory — population-coding beliefs to stimulation, delivering
observations as evidence, and decoding policy selection from territory firing —
injected behind Nous' existing client interface with `name`, bus subscriptions,
and `nous.out` event shapes unchanged. The backend SHALL default off (`"silicon"`)
until its decode-reliability gate passes.

#### Scenario: Event contract preserved

- **WHEN** Nous runs with `[backends].nous = "cl1"`
- **THEN** its `nous.out` events have the same schema as under `pymdp`

#### Scenario: Decode-reliability gate governs enablement

- **WHEN** decoded policy selection agrees with the intended expected-free-energy
  choice below the stated threshold across seeds
- **THEN** the `cl1` backend remains disabled and Nous stays on silicon

### Requirement: The substrate participates in the inference loop

The selected policy SHALL condition the next tick's stimulation, so the substrate
is part of the closed active-inference loop rather than a passive read-out.

#### Scenario: Policy conditions subsequent evidence

- **WHEN** a policy is decoded in one tick
- **THEN** the following tick's stimulation reflects that policy choice
