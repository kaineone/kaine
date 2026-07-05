# individuation-boundary Specification

## Purpose
TBD - created by archiving change individuation-boundary. Update Purpose after archive.
## Requirements
### Requirement: Null distribution from parent stochastic variation
The individuation test SHALL build a null distribution by sampling parent-vs-parent
preference divergence across `null_samples` runs with varied random seeds under
otherwise-controlled conditions, using the same divergence metric applied to the
fork.

#### Scenario: Null reflects parent variation
- **WHEN** the parent is sampled `null_samples` times on the battery
- **THEN** the null distribution contains `null_samples` divergence values
  computed with the configured metric

### Requirement: Significance via permutation test
The individuation test SHALL compute the fork-vs-parent divergence and report it
as significant only when it exceeds the `significance_percentile` (default 95th)
of the null distribution, returning the divergence, a p-value, the null summary,
and a significance flag. The instrument SHALL NOT itself decide fork sovereignty.

#### Scenario: A fork identical to its parent is not significant
- **WHEN** a fork's responses match the parent's distribution
- **THEN** the report's significance flag is false

#### Scenario: A strongly divergent fork is significant
- **WHEN** a fork's preference divergence exceeds the 95th percentile of the null
- **THEN** the report's significance flag is true and a p-value is included

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

