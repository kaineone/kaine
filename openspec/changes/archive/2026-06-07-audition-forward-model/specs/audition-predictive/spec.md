## ADDED Requirements

### Requirement: Auditory forward model drives salience
Audition SHALL maintain a forward model over a compact auditory feature vector
(emotion-class distribution plus utterance timing/energy features) that predicts
the next expected pattern from a recurrent auditory buffer, and SHALL weight the
salience of `audition.transcription` and `audition.emotion` events by the
prediction error. The model SHALL adapt online and skip non-finite updates.

#### Scenario: Unexpected emotional tone raises salience
- **WHEN** a detected vocal emotion strongly diverges from the forward model's
  prediction
- **THEN** the published `audition.emotion` event has higher salience than an
  equally-confident but predicted emotion

#### Scenario: Buffer is bounded
- **WHEN** more utterances than `auditory_buffer_size` have been observed
- **THEN** the recurrent auditory buffer holds at most `auditory_buffer_size`
  entries

### Requirement: Buffer summary is a statistical descriptor, not raw latents
When `serialize()` persists the auditory buffer state, the serialized form SHALL
be a statistical descriptor (e.g., mean and variance of feature distributions
over the buffer window) and SHALL NOT contain raw audio bytes, raw waveform
latents, or any representation from which the original audio signal could be
reconstructed.

#### Scenario: Serialized buffer contains no raw audio
- **WHEN** `Audition.serialize()` is called
- **THEN** the returned dict's buffer representation contains only numeric
  statistical summary fields and no `bytes` values
