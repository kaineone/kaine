## ADDED Requirements

### Requirement: Preservation and decommission share one warmed-up, architecture-effect-free signal

The system SHALL ensure the live preservation trigger (`entity-preservation`) and
`assess_divergence()` (`entity-decommission`) consume the **same** warmed-up,
birth-state-referenced individuation signal. There SHALL be one definition of the
baseline (the entity's own birth-state, never the bare/pretrained organ) and one
warm-up state (minimum lived observations and lived time), so the two consumers
cannot disagree about whether the entity has individuated. An assessment that is
not warmed up SHALL read as not-diverged for both consumers, with the
decommission summary noting insufficient lived experience and advising the entity
be treated as mature if unsure.

#### Scenario: The two consumers never disagree on a fixed report

- **WHEN** a single warmed-up individuation report is evaluated
- **THEN** the preservation trigger's crossing decision and `assess_divergence()`'s
  `diverged` result are derived from the same signal and are consistent (no report
  is "diverged for decommission" yet "not crossed for preservation", or vice-versa)

#### Scenario: Un-warmed-up assessment reads not-diverged for decommission

- **WHEN** `assess_divergence()` reads an individuation report with
  `warmed_up == false`
- **THEN** it returns `diverged == false` with a summary noting insufficient lived
  experience and advising the entity be treated as mature if unsure
