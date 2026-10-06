## ADDED Requirements

### Requirement: The decision model is not the organ
K1-Jev SHALL be trained offline, outside the entity runtime, on data that contains no entity data. It SHALL never be loaded as the language organ, never be applied as an adapter to the organ, and never condition Lingua's generation. The entity's sleep-cycle DPO SHALL remain the only training that changes the organ at runtime.

#### Scenario: No decision-model adapter on the organ
- **WHEN** the organ server starts
- **THEN** no K1-Jev adapter or weights are loaded into it
