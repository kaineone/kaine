## ADDED Requirements

### Requirement: The womb's state at birth is recorded
When the birth bloom completes, the stage file SHALL record the womb time at which the bloom ended (`womb_t_at_birth`), the womb seed and a digest of the womb parameters. The womb SHALL report that the bloom is complete, so a preservation taken after that report carries the record.

#### Scenario: A preserved newborn carries its birth state
- **WHEN** a being is preserved after its birth bloom completed
- **THEN** the preservation's stage file holds `womb_t_at_birth`, the womb seed and the parameter digest
