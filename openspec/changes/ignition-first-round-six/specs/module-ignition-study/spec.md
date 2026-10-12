## ADDED Requirements

### Requirement: The first round adds six held modules by default
Without an explicit order, `init` SHALL record the order episodic memory, world model, planning, self-model, social cognition, vocal modules. The effectors, perceptual locus and embodiment modules SHALL join only through an explicit order, once an effector, body or alternative sensor feed is attached.

#### Scenario: Default order
- **WHEN** a study is initialised without `--order`
- **THEN** its plan's order is episodic memory, world model, planning, self-model, social cognition, vocal modules.
