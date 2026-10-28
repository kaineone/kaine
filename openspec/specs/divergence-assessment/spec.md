# divergence-assessment Specification

## Purpose
Divergence-assessment defines the content-free divergence metric emitted whenever voice-alignment consolidation builds preference pairs, giving preservation and decommission a single warmed-up signal and shared thresholds for deciding whether an entity has drifted.

## Requirements

### Requirement: Preservation and decommission share one warmed-up, architecture-effect-free signal

The system SHALL ensure the live preservation trigger (`entity-preservation`) and
`assess_divergence()` (`entity-decommission`) consume the **same** warmed-up,
maturation-state-referenced individuation signal. There SHALL be one definition of the
baseline (the entity's own maturation-state, never the bare/pretrained organ) and one
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

### Requirement: Unreadable intent-log lines count as spoken evidence
The divergence assessment's spoken-evidence check SHALL treat an intent-log or corpus line that cannot be decrypted or parsed as evidence that the entity has spoken, so the voice arm votes diverged rather than abstaining.

#### Scenario: A log holding only an undecryptable line
- **WHEN** the only line in the intent log is an envelope that fails authentication
- **THEN** the voice arm votes diverged and the entity is assessed as diverged

### Requirement: An old consolidation record marks nothing
`assess_divergence` SHALL NOT read `state/sleep/consolidation_divergence.json`, and its signals SHALL carry no `consolidation_*` keys. The preservation monitor SHALL have no `consolidation` arm. A record left by an earlier boot SHALL remain a known state file for decommission, renames and lived-artifact checks.

#### Scenario: A record from an earlier boot
- **WHEN** the state tree holds a consolidation divergence record with rate 1.0 and no other arm is active
- **THEN** the assessment reports not diverged
