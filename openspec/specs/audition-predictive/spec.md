# audition-predictive Specification

## Purpose
The predictive-audition capability gives the Audition module a forward model over compact auditory features that predicts the next expected pattern and gates or weights the salience of `audition.transcription` and `audition.emotion` events by their prediction error.

## Requirements

### Requirement: Auditory forward model drives salience
Audition SHALL maintain a forward model over a compact auditory feature vector
(emotion-class distribution plus utterance timing/energy features) that predicts
the next expected pattern from a recurrent auditory buffer, and SHALL weight the
salience of `audition.transcription` and `audition.emotion` events by the
prediction error. The model SHALL adapt online and skip non-finite updates.

#### Scenario: Unexpected emotional tone raises salience (speech path)
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

### Requirement: The arousal-set auditory window shapes what is encoded
Audition's general acoustic path SHALL encode only the most recent fraction of each captured window, the fraction given by the arousal-to-window map, and never less than one analysis frame, and SHALL compute the published energy on the same span. The published `attended_window` SHALL report the fraction and `attended_seconds` the span encoded.

#### Scenario: Higher arousal encodes a shorter, more recent span
- **WHEN** the same captured window is perceived at arousal 0.0 and at arousal 1.0 with the default window range
- **THEN** the span encoded at arousal 1.0 is the most recent 15 percent of the window and the span at arousal 0.0 is the whole window

### Requirement: The tone feature is the utterance's length
The speech-path forward model's duration feature SHALL be the utterance's audio duration normalised over the maximum utterance length, and SHALL NOT depend on how long the classifiers took. Its checkpoint SHALL carry the feature-layout tag `utterance_duration_v2`, and a checkpoint without that tag SHALL be discarded so the model re-learns.

#### Scenario: Classifier latency does not change the feature
- **WHEN** the same utterance is classified once quickly and once slowly
- **THEN** the duration feature is the same

### Requirement: Every spectral band covers a distinct frequency bin
The fixed spectral encoder's band edges SHALL be strictly increasing FFT-bin indices that start above the DC bin, so no two bands read the same bins, and its `model_id` SHALL change whenever the band layout changes.

#### Scenario: No degenerate bands at 16 kHz
- **WHEN** the encoder runs with 32 bands, 25 ms frames and a 16 kHz sample rate
- **THEN** all 32 bands have distinct edge pairs and none includes the DC bin

### Requirement: A non-finite auditory input is skipped
When an acoustic embedding or a tone feature vector contains a non-finite value, Audition's forward model for that path SHALL skip the reading without appending it to the auditory buffer or updating any weight, SHALL clear its stored prediction, null prediction and context, and SHALL return an error of 0. The next reading then has no prediction to be scored against and makes no update. Only a defined error SHALL enter that path's running error window: the very first reading's error of 0 is defined (paper A.2), while a skipped reading and the first reading after a skip SHALL stay out of the window and SHALL publish `prediction_error` as null (on `audition.perception` for the acoustic path, on `audition.emotion` and `audition.transcription` for the tone path). For the acoustic path Audition SHALL publish no `context_gain`, `null_prediction_error` or `mean_prediction_error` for either report, SHALL NOT update the previous embedding or the change history on the skipped reading, and SHALL report a change score of 0 for it. The skipped report SHALL NOT be an alert by itself and SHALL carry no non-finite number.

#### Scenario: A NaN acoustic embedding leaves the model and the window untouched
- **WHEN** Audition, after acoustic reports that carry a gain, receives an acoustic embedding containing NaN
- **THEN** the acoustic forward model's buffer and weights, the running error window and the change history are unchanged, and the report carries a null prediction error, a change score of 0, no gain, no alert and no non-finite number

#### Scenario: A NaN tone feature vector is skipped
- **WHEN** the tone path's feature vector contains NaN
- **THEN** the tone forward model's buffer and weights and the tone error window are unchanged, the emotion event carries a null prediction error and no non-finite number, and the next window also stays out of the tone error window

#### Scenario: The gain resumes one reading after the skip
- **WHEN** two finite acoustic embeddings follow the skipped one
- **THEN** the first of them publishes a null prediction error, stays out of the window and reports no gain, and the second is scored, enters the window and reports a gain

#### Scenario: The hindsight pairing stays exact across a skip
- **WHEN** the live forward model and a widened copy see the same inputs, one of them non-finite
- **THEN** from the second finite input after the skip the copy's hindsight errors equal the live model's errors

### Requirement: The tone rule and the tone error ratio
The audition module SHALL compute for each tone event the running error ratio nu~utt_t of the tone path: its error over the mean of the last W_P defined errors including the current one, and 0 when the error is not defined or the mean is 0 (paper A.2). With `[audition].tone_rule = "categorical"` (the default) a tone event whose classified tone is not neutral SHALL have the alert intensity and `alert` true, and a neutral one SHALL have Gamma_Aud(nu~utt_t) and `alert` false. With `tone_rule = "error_ratio"` (the tone variant of the on arm, paper A.8) every tone event SHALL have Gamma_Aud(nu~utt_t) and `alert` false. Each `audition.emotion` event SHALL carry `tone_error_ratio` (nu~utt_t), `tone_rule`, `entity_time_s` (the entity time of the event, so the analysis can count it after T_learn), and `classified`, which is false when the classifier failed or reported a degraded result. A failed classification SHALL keep the alert intensity under the default rule and SHALL be graded by Gamma_Aud(nu~utt_t) with `alert` false under `error_ratio`. A tone event SHALL NOT carry `normalised_error`, which the affect module reads as appraisal novelty. Any other `tone_rule` value SHALL be refused at construction.

#### Scenario: An emotional tone in the variant
- **WHEN** Audition with `tone_rule = "error_ratio"` classifies an angry tone whose error equals the running mean
- **THEN** the event's intensity is Gamma_Aud(1), halfway between the baseline and the alert level, and `alert` is false

#### Scenario: The default rule
- **WHEN** Audition with the default rule classifies a happy tone
- **THEN** the event has the alert intensity and `alert` true
