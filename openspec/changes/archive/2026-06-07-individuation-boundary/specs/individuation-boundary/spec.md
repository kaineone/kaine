## ADDED Requirements

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
