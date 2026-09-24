## ADDED Requirements

### Requirement: Soma accepts an injected forward model
Soma's constructor SHALL accept an optional `forward_model` object. When it is `None`, Soma SHALL build its default `SubstrateForwardModel` with the configured `forward_model_units`, as before. When it is provided, Soma SHALL use it in place of the default and SHALL call only the interface Soma already uses on its forward model (`step`, `prediction_error_to_salience`, `suspended`, `adaptation_steps`, `state_dict`, `load_state_dict`).

#### Scenario: Default unchanged
- **WHEN** Soma is constructed without `forward_model`
- **THEN** it builds a `SubstrateForwardModel` exactly as it does today

#### Scenario: Injected model used
- **WHEN** Soma is constructed with `forward_model=model`
- **THEN** each interoceptive tick calls `model.step` and no `SubstrateForwardModel` is built
