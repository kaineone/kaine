# audition Specification

## Purpose
Audition is KAINE's hearing module. This capability fixes its module name, its output stream `audition.out` and its event names, and marks events as degraded when a model is missing.

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

### Requirement: Acoustic perception reports carry the change ratio
Every `audition.perception` event SHALL carry `normalised_change`, the acoustic change score divided by the running mean of acoustic change scores used by the acoustic change alert, or 0.0 when that mean is 0 (paper A.2).

#### Scenario: An acoustic onset carries a large change ratio
- **WHEN** four steady windows are followed by a very different window
- **THEN** the fifth `audition.perception` carries a `normalised_change` of at least the acoustic change alert factor

#### Scenario: The first report carries zero
- **WHEN** the first window is processed
- **THEN** its `audition.perception` carries `normalised_change` 0.0
