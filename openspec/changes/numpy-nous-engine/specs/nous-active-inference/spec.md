## ADDED Requirements

### Requirement: A JAX-free Nous engine computes what the pymdp engine computes
KAINE SHALL provide a NumPy active-inference engine, selected by `[nous].backend = "numpy"`, that reproduces the pymdp engine's state inference, per-policy expected free energy (utility, state information gain, and parameter information gain for learning models), policy enumeration, transition learning, prior propagation and learned-state format for KAINE's generative models, and that needs neither JAX nor pymdp. Its agreement with the pymdp engine SHALL be verified against golden fixtures recorded from the pymdp engine, on every host. A learned state saved by either engine SHALL load into the other.

#### Scenario: A host without JAX
- **WHEN** Nous runs with `backend = "numpy"` where JAX cannot be imported
- **THEN** it infers, plans, learns and publishes as it does with the pymdp engine, and the extras check does not require the `reasoning` extra

#### Scenario: The same decisions
- **WHEN** both engines process the golden observation sequence from the same model
- **THEN** their posteriors, per-policy EFE and learned transitions agree within 1e-4 and they choose the same actions

#### Scenario: A being moves between hosts
- **WHEN** a being preserved on a JAX host is revived on a host using the NumPy engine
- **THEN** its learned model and carried belief load, and its next decision matches the one the pymdp engine would make
