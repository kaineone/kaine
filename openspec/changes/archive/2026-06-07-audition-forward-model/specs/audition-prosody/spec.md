## ADDED Requirements

### Requirement: Speaker prosody extracted in memory as numeric features
When `prosody_enabled` is true, Audition SHALL extract per-utterance prosodic
features (an F0/pitch contour summary via `librosa.pyin`, energy via RMS, and
speaking rate via `librosa.beat.tempo`) from captured audio held as a NumPy
array in memory, and SHALL publish them as an `audition.prosody` event
containing numeric features only. No raw audio SHALL be written to disk or
placed on the bus, and no `NamedTemporaryFile` or `.wav` file SHALL be created
during prosody extraction or STT processing.

#### Scenario: Prosody event carries only numeric features
- **WHEN** Audition processes an utterance with `prosody_enabled` true
- **THEN** the published `audition.prosody` payload contains numeric prosodic
  features and no field whose value is a `bytes` object

#### Scenario: Disabled prosody publishes nothing
- **WHEN** `prosody_enabled` is false and an utterance is processed
- **THEN** no `audition.prosody` event is published

#### Scenario: No raw audio written to disk during STT or prosody
- **WHEN** Audition processes any utterance (transcription or prosody path)
- **THEN** no file is created on disk containing raw audio bytes (no NamedTemporaryFile, no .wav writes)
