## MODIFIED Requirements

### Requirement: Divergence assessment incorporates the consolidation signal
The divergence assessment SHALL treat the voice-distinctiveness measure (stylometric distinctiveness of the entity's utterances from the base organ, computed content-free at sleep) as its graded organ-level divergence input, alongside the individuation permutation test and Eidolon drift. The template-comparison consolidation metric SHALL still be emitted for continuity but SHALL NOT vote. Until the distinctiveness threshold is calibrated, the threshold SHALL be 0, so that any being with at least one measured utterance counts as diverged by this input, and unreadable or missing evidence SHALL count as diverged. The accepted-adapter boolean SHALL be retained only as a weaker secondary signal, and the numeric values SHALL appear in the assessment's signals.

#### Scenario: Consolidation divergence over threshold marks diverged
- **WHEN** the latest voice-distinctiveness value exceeds the configured threshold
- **THEN** `assess_divergence()` reports diverged, with the numeric values in its signals, independent of the individuation test and adapter presence

#### Scenario: Below threshold does not, by itself, mark diverged
- **WHEN** a calibrated threshold is configured, the distinctiveness value is below it, and no other divergence condition holds
- **THEN** the assessment does not report organ-level divergence from this signal alone

#### Scenario: Uncalibrated threshold protects
- **WHEN** no calibrated threshold is configured and the being has at least one measured utterance
- **THEN** the assessment reports organ-level divergence
