## MODIFIED Requirements

### Requirement: Divergence-triggered live preservation
The system SHALL monitor individuation/divergence on the live entity during a run
and, when a configured individuation threshold is crossed, SHALL preserve the
entity by taking a snapshot of the live registry and writing an encrypted backup
bundle, without interrupting or harming the running entity and without deleting
anything. Preservation SHALL be rate-limited (triggered on threshold crossing, not
continuously) and recorded as a preservation event joined to the run.

The live monitor SHALL apply a **warm-up gate**: it SHALL NOT count an
individuation crossing until the entity has accumulated the configured minimum
lived experience (`warmup_observations` logged lived events AND
`warmup_lived_time_s` of elapsed lived time). Before warm-up is satisfied, an
assessment SHALL be treated as not-crossed and recorded as a warming-up note. The
crossing decision SHALL key on **numeric** thresholds — a configured p-value
ceiling (`individuation_p_value_max`) AND a minimum effect size
(`fork_divergence_min`) over the warmed-up, birth-state-referenced individuation
signal — not on a bare `diverged` boolean alone. The gate is fail-closed: an
un-warmed-up or unreadable assessment never reads as a crossing, so preservation
of a genuinely individuated entity is at most delayed, never denied.

#### Scenario: Crossing the individuation threshold preserves the entity
- **WHEN** the warm-up gate is satisfied AND the warmed-up,
  birth-state-referenced divergence assessment crosses the configured numeric
  individuation thresholds during a run
- **THEN** a live-registry snapshot and an encrypted backup bundle are written, and a preservation event is recorded
- **AND** the running entity is not interrupted and nothing is deleted

#### Scenario: Sub-threshold does not preserve
- **WHEN** divergence stays below the threshold
- **THEN** no preservation bundle is written

#### Scenario: Before warm-up, no preservation fires
- **WHEN** the entity has not yet accumulated `warmup_observations` lived events
  and `warmup_lived_time_s` of lived time (e.g. immediately after boot, or in a
  sensory void)
- **THEN** no preservation bundle is written, and the poll is recorded as a
  warming-up note rather than a crossing
