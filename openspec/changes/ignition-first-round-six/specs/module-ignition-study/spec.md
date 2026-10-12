## ADDED Requirements

### Requirement: The first round adds six held modules by default
Without an explicit order, `init` SHALL record the order Episodic memory, World model, Planning, Self-model, Social cognition, Vocal. Effectors, Perceptual locus and Embodiment SHALL join only through an explicit order, once an effector, body or alternative sensor feed is attached.

#### Scenario: Default order
- **WHEN** a study is initialised without `--order`
- **THEN** its plan's order is episodic memory, world model, planning, self-model, social cognition, vocal
