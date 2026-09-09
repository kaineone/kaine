## ADDED Requirements

### Requirement: Transcription is gateable

Audition SHALL provide a configuration gate that, when transcription is disabled,
skips the speech-to-text path entirely: no `audition.transcription` event is
published and no STT model is invoked. The acoustic-perception path
(`audition.perception` prediction error) and the affect signals
(`audition.emotion`, `audition.prosody`) SHALL be unaffected. The STT code SHALL
remain present (gated off), not removed.

#### Scenario: Transcription disabled publishes no transcript

- **WHEN** Audition runs with transcription disabled and processes audio
- **THEN** it publishes no `audition.transcription` event and invokes no STT model

#### Scenario: Perception path unaffected by the gate

- **WHEN** Audition runs with transcription disabled and acoustic perception enabled
- **THEN** it still publishes `audition.perception` prediction-error events

#### Scenario: Default behavior preserved

- **WHEN** Audition runs with transcription enabled (the default)
- **THEN** it publishes `audition.transcription` exactly as before this change
