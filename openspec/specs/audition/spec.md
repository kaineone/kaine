# audition Specification

## Purpose
TBD - created by archiving change rename-audition-vox. Update Purpose after archive.
## Requirements
### Requirement: Audition module identity
The hearing organ SHALL be the module named `audition` (renamed from
`audio_in`), implemented by the `Audition` class, publishing to the
`audition.out` stream. Its behavior (Speaches/distil-Whisper STT, emotion2vec+
classification, VAD-gated capture) SHALL be unchanged by the rename.

#### Scenario: Module reports its name
- **WHEN** the `Audition` module is constructed
- **THEN** its `name` attribute equals `"audition"`

#### Scenario: Output stream follows the name
- **WHEN** Audition publishes any event
- **THEN** it is written to the `audition.out` stream

### Requirement: Audition event-type names
Audition SHALL publish transcription events with type
`audition.transcription` and vocal-emotion events with type
`audition.emotion`. No event with type `audio.in.*` SHALL be published after
this change.

#### Scenario: Transcription event type
- **WHEN** Audition transcribes an utterance
- **THEN** the published event's `type` equals `"audition.transcription"`

#### Scenario: Emotion event type
- **WHEN** Audition classifies vocal emotion
- **THEN** the published event's `type` equals `"audition.emotion"`

### Requirement: audition.emotion SHALL carry degraded flag when model absent

`Audition` SHALL include `"degraded": true` in the `audition.emotion` event
payload when the emotion classification model is unavailable (funasr not
installed or not yet loaded).  This distinguishes a placeholder result from a
real low-confidence classification and allows downstream consumers to gate on
the flag.

#### Scenario: emotion model absent

- **WHEN** `Audition._publish_emotion()` is called with an `EmotionResult`
  whose `raw` field contains `"degraded": true`
- **THEN** the published `audition.emotion` payload carries `"degraded": true`

#### Scenario: emotion model present

- **WHEN** `Audition._publish_emotion()` is called with a real `EmotionResult`
  (no `degraded` key in `raw`)
- **THEN** the published `audition.emotion` payload does NOT carry `"degraded"`

