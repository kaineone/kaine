## ADDED Requirements

### Requirement: Divergence assessment includes the voice-distinctiveness arm
The divergence assessment SHALL include a voice-distinctiveness arm alongside the individuation permutation test and self-model drift: the stylometric distinctiveness of the entity's utterances from the base organ, computed content-free at sleep, SHALL mark organ-level divergence when it crosses its threshold. Until that threshold is calibrated it SHALL be 0, so any entity with at least one measured utterance counts as diverged by it, and unreadable or missing distinctiveness evidence SHALL count as diverged. The accepted-adapter boolean SHALL be retained only as a weaker secondary signal, and the arm's numeric values SHALL appear in the assessment's signals. There SHALL be no consolidation (template-comparison) arm: voice adaptation computes no organ-level divergence until a validated preference source exists (paper section 3.5).

#### Scenario: Below threshold does not, by itself, mark diverged
- **WHEN** the voice-distinctiveness arm is below a calibrated threshold and no other divergence condition holds
- **THEN** the assessment does not report organ-level divergence from this signal alone

#### Scenario: Uncalibrated distinctiveness protects
- **WHEN** no calibrated distinctiveness threshold is configured and the entity has at least one measured utterance
- **THEN** the assessment reports organ-level divergence
