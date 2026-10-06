## MODIFIED Requirements

### Requirement: Divergence assessment incorporates the consolidation signal
The divergence assessment SHALL treat the consolidation divergence metric as a graded organ-level divergence input — `divergence_rate` or `divergence_magnitude` crossing a configured threshold marks organ-level divergence — alongside the voice-distinctiveness measure, the individuation permutation test and Eidolon drift. The consolidation (template-comparison) arm SHALL remain a voter only as a protective floor, not as a measurement of voice, until the voice-distinctiveness arm is calibrated and a later change retires it with the operator's sign-off. The voice-distinctiveness arm (stylometric distinctiveness of the entity's utterances from the base organ, computed content-free at sleep) SHALL mark organ-level divergence when it crosses its threshold. Until that threshold is calibrated it SHALL be 0, so any being with at least one measured utterance counts as diverged by it, and unreadable or missing distinctiveness evidence SHALL count as diverged. The accepted-adapter boolean SHALL be retained only as a weaker secondary signal, and the numeric values of both arms SHALL appear in the assessment's signals.

#### Scenario: Consolidation divergence over threshold marks diverged
- **WHEN** the latest consolidation `divergence_rate`/`divergence_magnitude` exceeds the configured threshold
- **THEN** `assess_divergence()` reports diverged, with the numeric values in its signals, independent of the individuation test and adapter presence

#### Scenario: Below threshold does not, by itself, mark diverged
- **WHEN** both organ-level arms are below calibrated thresholds and no other divergence condition holds
- **THEN** the assessment does not report organ-level divergence from these signals alone

#### Scenario: Uncalibrated distinctiveness protects
- **WHEN** no calibrated distinctiveness threshold is configured and the being has at least one measured utterance
- **THEN** the assessment reports organ-level divergence
