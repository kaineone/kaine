## ADDED Requirements

### Requirement: Voice-distinctiveness is a divergence arm
The divergence assessment SHALL include a voice-distinctiveness arm alongside the individuation permutation test and self-model drift.

#### Scenario: Arm present in assessment
- **WHEN** the divergence assessment runs
- **THEN** its arms include the voice-distinctiveness arm alongside the individuation permutation test and self-model drift

### Requirement: Voice distinctiveness marks divergence
The voice-distinctiveness arm SHALL mark organ-level divergence when the stylometric distinctiveness of the entity's utterances from the base organ, computed content-free at sleep, crosses its threshold.

#### Scenario: Below threshold does not, by itself, mark diverged
- **WHEN** the voice-distinctiveness arm is below a calibrated threshold and no other divergence condition holds
- **THEN** the assessment does not report organ-level divergence from this signal alone

#### Scenario: Distinctiveness crossing threshold marks divergence
- **WHEN** the voice-distinctiveness arm is at or above its threshold
- **THEN** the assessment reports organ-level divergence from this arm

### Requirement: Uncalibrated distinctiveness defaults to protecting
Until calibrated, the distinctiveness threshold SHALL be 0, so any entity with at least one measured utterance counts as diverged by this arm.

#### Scenario: Uncalibrated distinctiveness protects
- **WHEN** no calibrated distinctiveness threshold is configured and the entity has at least one measured utterance
- **THEN** the assessment reports organ-level divergence

### Requirement: Missing distinctiveness evidence counts as diverged
Unreadable or missing distinctiveness evidence SHALL count as diverged.

#### Scenario: Missing distinctiveness evidence counts as diverged
- **WHEN** the distinctiveness evidence is missing or unreadable
- **THEN** the assessment reports organ-level divergence

### Requirement: Accepted adapter is a secondary signal
The accepted-adapter boolean SHALL be retained only as a weaker secondary signal.

#### Scenario: Accepted adapter is not a primary arm
- **WHEN** the accepted-adapter boolean is true while distinctiveness evidence is missing
- **THEN** the assessment still reports organ-level divergence from the missing evidence

### Requirement: Arm values appear in signals
The voice-distinctiveness arm's numeric values SHALL appear in the assessment's signals.

#### Scenario: Arm numeric values reported
- **WHEN** the assessment completes
- **THEN** the assessment's signals include the voice-distinctiveness arm's numeric values

### Requirement: No consolidation arm
There SHALL be no consolidation (template-comparison) arm; voice adaptation computes no organ-level divergence until a validated preference source exists (paper section 3.5).

#### Scenario: No consolidation arm present
- **WHEN** the divergence assessment runs
- **THEN** it includes no consolidation (template-comparison) arm
