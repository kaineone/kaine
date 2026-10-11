## ADDED Requirements

### Requirement: Coherence counts only fresh phase samples
The coherence scorer SHALL treat a module's phase sample as fresh only when it differs from that module's previous sample, and SHALL compute the phase-locking value of a pair of modules over the ticks in the window where both samples are fresh. When a pair has fewer than three jointly fresh ticks, the pair SHALL contribute the neutral phase-locking value, the value that `factor_from_plv` maps to a factor of exactly 1.0 (clipped to `[0, 1]`). A source with no partner that yields evidence, including a source alone in its cohort, SHALL receive the neutral factor, which is 1.0 whenever `coherence_floor <= 1 <= coherence_ceiling` and equals the common bound in the unit-gain null control.

#### Scenario: Frozen phases are not perfect locking
- **WHEN** two modules' phases stay constant across the whole window because neither published
- **THEN** each receives a coherence factor of 1.0, not the ceiling

#### Scenario: A lone source is not boosted
- **WHEN** a candidate's source is the only source in its cohort
- **THEN** its coherence factor is 1.0 at the default bounds

#### Scenario: Rotating locked sources still win
- **WHEN** two modules publish every tick with phases that advance together and a third advances independently
- **THEN** the two locked modules receive a higher factor than the desynchronized one
