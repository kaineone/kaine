## ADDED Requirements

### Requirement: The first round adds six held modules by default
Without an explicit order, `init` SHALL record the order Mnemos, Phantasia, Nous, Eidolon, Empatheia, Vox. Praxis, Perception and Mundus SHALL join only through an explicit order, once an effector, body or alternative sensor feed is attached.

#### Scenario: Default order
- **WHEN** a study is initialised without `--order`
- **THEN** its plan's order is mnemos, phantasia, nous, eidolon, empatheia, vox
