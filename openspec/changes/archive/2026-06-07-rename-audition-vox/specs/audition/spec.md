## ADDED Requirements

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
