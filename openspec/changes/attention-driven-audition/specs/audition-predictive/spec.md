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
