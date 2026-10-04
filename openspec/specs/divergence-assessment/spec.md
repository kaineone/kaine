# divergence-assessment Specification

## Purpose
Divergence-assessment defines the content-free divergence metric emitted whenever voice-alignment consolidation builds preference pairs, giving preservation and decommission a single warmed-up signal and shared thresholds for deciding whether an entity has drifted.

## Requirements

### Requirement: Consolidation divergence metric
The voice-alignment consolidation phase SHALL emit a content-free divergence
metric whenever it builds preference pairs — including when training is skipped,
disabled, or the resulting adapter is rejected — carrying `records_scanned`,
`usable_pairs`, `divergence_rate` (usable / scanned), and a semantic
`divergence_magnitude` (mean cosine distance over the kept pairs, null when the
semantic embedder is unavailable). The metric SHALL contain only aggregate numbers
— never the prompt, chosen, or rejected utterance text.

#### Scenario: Divergent utterances produce a nonzero metric
- **WHEN** an intent-expression log contains records whose conditioned output differs from the bare organ output
- **THEN** the emitted metric's `usable_pairs` counts exactly those records and `divergence_rate` is `usable_pairs / records_scanned`

#### Scenario: Metric is emitted even when training does not run
- **WHEN** voice-alignment is skipped (disabled / not approved) or the adapter is rejected by the capability/abliteration gates
- **THEN** the consolidation divergence metric is still emitted (the divergence occurred independent of training)

#### Scenario: Metric carries no utterance content
- **WHEN** the consolidation divergence event/record is produced
- **THEN** it contains only numeric aggregates and no prompt/chosen/rejected text

### Requirement: Divergence assessment incorporates the consolidation signal
The divergence assessment SHALL treat the consolidation divergence metric as a
graded organ-level divergence input — `divergence_rate` or `divergence_magnitude`
crossing a configured threshold marks organ-level divergence — alongside the
individuation permutation test and Eidolon drift. The accepted-adapter boolean
SHALL be retained only as a weaker secondary signal, and the numeric consolidation
values SHALL appear in the assessment's signals.

#### Scenario: Consolidation divergence over threshold marks diverged
- **WHEN** the latest consolidation `divergence_rate`/`divergence_magnitude` exceeds the configured threshold
- **THEN** `assess_divergence()` reports diverged, with the numeric consolidation values in its signals, independent of the individuation test and adapter presence

#### Scenario: Below threshold does not, by itself, mark diverged
- **WHEN** the consolidation divergence is below the configured threshold and no other divergence condition holds
- **THEN** the assessment does not report organ-level divergence from this signal alone

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

### Requirement: Live preservation and decommission use the same consolidation thresholds
The live divergence monitor SHALL assess divergence with the consolidation thresholds configured in `[hypnos.voice_alignment]` (`consolidation_divergence_rate_threshold`, `consolidation_divergence_magnitude_threshold`), read the same way the decommission CLI reads them, so the two consumers reach the same verdict on the same records.

#### Scenario: A lowered rate threshold is honoured live
- **WHEN** `consolidation_divergence_rate_threshold = 0.2` and the latest consolidation record has `divergence_rate = 0.3`
- **THEN** the live monitor's assessment reports organ-level divergence, as the decommission CLI's does
