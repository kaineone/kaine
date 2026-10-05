# audition-predictive

## MODIFIED Requirements

### Requirement: Auditory forward model drives salience

Audition SHALL maintain a forward model that predicts the next expected acoustic
embedding from a recurrent auditory buffer, and SHALL set the salience of what it
hears from the prediction error over that embedding — so the salience covers any
sound, not only speech. When general auditory perception is disabled, the forward
model MAY fall back to the compact speech-shaped feature vector (emotion-class
distribution plus utterance timing/energy) that weights `audition.transcription`
and `audition.emotion` salience. The model SHALL adapt online and skip non-finite
updates.

#### Scenario: An unexpected sound raises salience

- **WHEN** an acoustic embedding strongly diverges from the forward model's
  prediction (a novel or sudden sound)
- **THEN** the published salience for that sound is higher than that of an
  equally-loud but predicted sound, whether or not it is speech

#### Scenario: Unexpected emotional tone raises salience (speech path)

- **WHEN** general auditory perception is disabled and a detected vocal emotion
  strongly diverges from the forward model's prediction
- **THEN** the published `audition.emotion` event has higher salience than an
  equally-confident but predicted emotion

#### Scenario: Buffer is bounded

- **WHEN** more windows than `auditory_buffer_size` have been observed
- **THEN** the recurrent auditory buffer holds at most `auditory_buffer_size`
  entries

## ADDED Requirements

### Requirement: The acoustic forward model persists with the being
Audition SHALL serialize the acoustic forward model's weights and statistical buffer summary keyed by the encoder's `model_id`, and SHALL restore the running encoder's entry when its tensor shapes match the running model. An entry whose shapes do not match SHALL be discarded with a logged warning, and the model SHALL learn afresh. Entries for other encoders SHALL be carried forward unchanged. The serialized form SHALL contain no raw audio and no raw embeddings.

#### Scenario: Round-trip
- **WHEN** an Audition that has adapted its acoustic forward model is serialized and a new instance with the same encoder restores the state
- **THEN** both instances predict the same next embedding for the same input

#### Scenario: Shape mismatch
- **WHEN** a restored entry for the running encoder has tensor shapes that do not match the running model
- **THEN** the entry is discarded with a warning and restore does not raise

#### Scenario: Switching encoder keeps the other model
- **WHEN** a being serialized under encoder A is restored under encoder B and serialized again
- **THEN** the new state still holds encoder A's entry unchanged

### Requirement: Auditory adaptation pauses during sleep
Audition SHALL suspend adaptation of its forward models from `hypnos.sleep.started` until `hypnos.sleep.completed`, while continuing to perceive and to compute prediction error.

#### Scenario: No learning while asleep
- **WHEN** `hypnos.sleep.started` has been received and Audition perceives windows
- **THEN** the forward models' weights do not change until `hypnos.sleep.completed` is received
