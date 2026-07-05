# divergence-assessment (delta)

## ADDED Requirements

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
