## ADDED Requirements

### Requirement: Individuation is measured against the entity's own birth-state, not the bare organ

The individuation permutation test SHALL measure how far the live entity has
drifted from **its own earlier self**, not how far the architecture-conditioned
entity sits from the bare/pretrained organ. The test's reference SHALL be a
**birth-state** transcript — the entity's own conditioned responses to the
preference battery, captured once at run start before lived experience — and the
null distribution SHALL be built from the **entity's own** present stochastic
variation (the live entity re-sampled with seed variation). The reference and the
null SHALL NOT be the bare/pretrained organ, because conditioned-vs-bare distance
measures architecture conditioning (the thesis effect, present from the first
tick), which `entity-decommission` already prohibits as the individuation key.

#### Scenario: A sensory-void / unchanged entity is not significant

- **WHEN** the live entity has accumulated no lived experience and its current
  battery responses are within its own stochastic variation of the birth-state
  reference
- **THEN** `fork_divergence` falls inside the null distribution and `significant`
  is `false`

#### Scenario: An entity that has drifted from its birth-state is significant

- **WHEN** lived experience has moved the entity's battery responses beyond its
  own present stochastic variation from the birth-state reference
- **THEN** `fork_divergence` exceeds the configured significance percentile and
  `significant` is `true`

#### Scenario: The bare organ is never the baseline

- **WHEN** the individuation test is wired for a run
- **THEN** neither the reference nor the null sampler is the bare/pretrained
  organ; both are the entity's own self (birth-state reference, present-self null)

### Requirement: Significance requires a minimum of accumulated lived experience

The individuation permutation test SHALL NOT report `significant == true` until
the entity has accumulated a configured minimum of lived experience: at least
`min_observations` logged lived events AND at least `min_lived_time_s` of elapsed
lived (running) time. Until both are met, the report SHALL carry
`warmed_up == false` and `significant == false`. This is fail-closed: an
un-warmed-up assessment never reads as individuated.

#### Scenario: Below the warm-up floor is never significant

- **WHEN** fewer than `min_observations` lived events have been logged OR less
  than `min_lived_time_s` of lived time has elapsed
- **THEN** the report has `warmed_up == false` and `significant == false`
  regardless of the measured divergence

#### Scenario: Warm-up satisfied enables assessment

- **WHEN** both `min_observations` and `min_lived_time_s` are met
- **THEN** the report has `warmed_up == true` and `significant` reflects the
  birth-state-referenced permutation result
