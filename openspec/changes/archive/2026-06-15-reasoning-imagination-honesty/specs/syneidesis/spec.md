## ADDED Requirements

### Requirement: Placeholder salience factors are disclosed at runtime

`RuleBasedSalience` SHALL emit a one-time `log.warning` at construction when
the injected `goal_scorer` is a `StaticGoalScorer` or the `thymos_modulator`
is a `StaticThymosModulator`, naming which factor(s) are bypassed and the
constant value returned. This makes the degraded two-factor salience mode
visible in operator logs without requiring source inspection.

`RuleBasedSalience` implements a four-factor product salience:
`intensity × novelty × goal_relevance × thymos_modulation`. When either
factor is a static placeholder (returning a constant), the live salience is
effectively reduced to `intensity × novelty`. The scoring math is unchanged;
this requirement governs disclosure only.

#### Scenario: Static goal scorer warns at construction
- **WHEN** `RuleBasedSalience` is constructed with a `StaticGoalScorer`
- **THEN** a `WARNING`-level log message names `StaticGoalScorer` and the
  bypassed `goal_relevance` factor

#### Scenario: Static thymos modulator warns at construction
- **WHEN** `RuleBasedSalience` is constructed with a `StaticThymosModulator`
- **THEN** a `WARNING`-level log message names `StaticThymosModulator` and the
  bypassed `thymos_modulation` factor

#### Scenario: Real scorers emit no warning
- **WHEN** `RuleBasedSalience` is constructed with non-Static scorers
- **THEN** no warning is emitted
