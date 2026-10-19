# vision-predictive Specification

## Purpose
This capability gives the vision module a visual forward model that predicts the next latent from the current latent and recurrent visual buffer, driving salience from prediction error. The vision module adapts the model online with a single gradient step per clip latent, summarizes the buffer as a statistical descriptor for serialization, and binds the latent dimension to the active encoder.

## Requirements

### Requirement: Visual forward model predicts next latent
The vision module SHALL maintain a forward model that predicts the next visual latent from the
current latent and a recurrent visual buffer, and SHALL adapt it online with a
single small gradient step per produced clip latent, skipping any non-finite
update. The forward model's latent dimension SHALL follow the active encoder's
`latent_dim` (768 for the default temporally-native encoder), derived at
initialization rather than hardcoded. The visual encoder SHALL remain frozen (no
gradients flow into it). A persisted forward-model checkpoint whose tensor shapes
do not match the running encoder's `latent_dim` SHALL be discarded with a warning
(the online model re-learns from scratch) rather than loaded — throwing a shape
error or silently corrupting state is not permitted.

This requirement covers ONLY the module-level VISUAL next-latent predictor. It is
distinct from and does not affect the DreamerV3 world model of the world model module, which predicts
the fused whole-workspace state; the two predictors SHALL NOT be conflated.

#### Scenario: Encoder stays frozen
- **WHEN** the forward model takes an online update step
- **THEN** no parameter of the visual encoder is modified

#### Scenario: Forward-model dimension follows the encoder
- **WHEN** the default 768-dim temporally-native encoder is active
- **THEN** the forward model's input and output latent dimension is 768, taken
  from the encoder rather than a hardcoded 384

#### Scenario: Mismatched checkpoint is discarded, not loaded
- **WHEN** `Vision.deserialize` receives a forward-model checkpoint whose tensor
  shapes do not match the running encoder's `latent_dim`
- **THEN** the checkpoint's forward-model weights are discarded with a warning and
  the model continues to learn online, without raising a shape error

#### Scenario: Buffer is bounded
- **WHEN** more clip latents than `visual_buffer_size` have been observed
- **THEN** the recurrent visual buffer holds at most `visual_buffer_size` latents

### Requirement: Salience is driven by prediction error
The vision module's event salience SHALL be driven by the visual prediction error (the
magnitude of the predicted-minus-actual latent), such that a predictable change
yields lower salience than an equally large but unpredicted change. The alert
criterion SHALL be relative to the module's own rolling baseline of prediction
error rather than an absolute constant, so it is independent of the encoder's
embedding scale (InternVideo-Next clip latent, foveal gist, or DINOv2). A
perceptual discontinuity SHALL raise salience above baseline; a steady,
well-predicted stream SHALL remain at baseline. Salience MUST NOT be a constant
independent of the stimulus. The legacy `change_score` and `habituation_score`
SHALL remain on the event payload for diagnostics.

#### Scenario: Predictable motion is less salient than surprise
- **WHEN** a smoothly predictable latent trajectory and an abrupt unpredicted
  latent jump produce equal raw cosine change
- **THEN** the unpredicted jump yields strictly higher event salience

#### Scenario: Diagnostics fields retained
- **WHEN** the vision module publishes a report
- **THEN** the payload still contains `change_score` and `habituation_score`

#### Scenario: A perceptual discontinuity alerts

- **WHEN** the perceptual stream contains a change whose prediction error is at
  least k times the module's rolling-window baseline (e.g. a scene cut)
- **THEN** the emitted `vision.report` carries the alert salience, not the baseline

#### Scenario: A steady stream stays at baseline

- **WHEN** the perceptual stream is steady and well-predicted (prediction error near
  the rolling baseline)
- **THEN** the emitted `vision.report` carries the baseline salience

#### Scenario: Alert criterion is embedding-scale-agnostic

- **WHEN** the same step-change is presented under different encoders (temporal clip
  latent vs foveal gist)
- **THEN** both produce an alert-level salience — the criterion does not depend on an
  absolute threshold tuned to one embedding space

#### Scenario: Perception can drive the workspace competition

- **WHEN** an alert-level perceptual event enters the workspace
- **THEN** its competition score reflects the elevated salience and can vary with the
  stimulus, rather than resting at the fixed `intensity × novelty` baseline product

### Requirement: Buffer summary serialized as statistical descriptor
When `serialize()` persists the visual buffer state, the serialized form SHALL
be a statistical descriptor (e.g., mean and variance of latent features over the
buffer window) and SHALL NOT contain raw DINOv2 latent tensors or any
representation from which the original video frames could be meaningfully
reconstructed.

#### Scenario: Serialized buffer contains only statistical summaries
- **WHEN** `Vision.serialize()` is called
- **THEN** the buffer representation in the returned dict contains only numeric
  statistical summary fields (mean, variance, or equivalent) and no raw latent
  tensors

### Requirement: A non-finite clip latent is skipped
When the clip latent contains a non-finite value, the vision module's forward model SHALL skip the reading without appending it to the visual buffer or updating any weight, SHALL clear its stored prediction, null prediction and context, and SHALL return an error of 0. The next reading then has no prediction to be scored against and makes no update. Only a defined error SHALL enter the vision module's running error window: the very first reading's error of 0 is defined (paper A.2), while a skipped reading and the first reading after a skip have no defined error, SHALL stay out of the window, and SHALL publish `prediction_error` as null with a `normalised_error` of 0. The vision module SHALL publish no `context_gain`, `null_prediction_error` or `mean_prediction_error` for either report. The skipped reading SHALL NOT update the change detector, the change history or the habituator; its change score SHALL be 0 and its habituation score SHALL be the last one the vision module published, or null before the first. A report SHALL carry no non-finite number: a non-finite `latent`, `peripheral` or `foveal` vector SHALL be published as null. The skipped report SHALL NOT be an alert by itself.

#### Scenario: A NaN latent leaves the model and the window untouched
- **WHEN** the vision module, after reports that carry a gain, receives a clip latent containing NaN
- **THEN** the forward model's buffer and weights, the running error window, the change history and the habituator's window are unchanged, and the report carries a null prediction error, a change score of 0, the previous habituation score, a null latent, no gain, no alert and no non-finite number

#### Scenario: The gain resumes one reading after the skip
- **WHEN** two finite clip latents follow the skipped one
- **THEN** the first of them publishes a null prediction error, stays out of the window and reports no gain, and the second is scored, enters the window and reports a gain

#### Scenario: Periodic gaps put no zeros in the window
- **WHEN** non-finite latents recur, each followed by two finite ones
- **THEN** the running error window holds only the first reading's 0 and the errors of the scored readings

#### Scenario: The hindsight pairing stays exact across a skip
- **WHEN** the live forward model and a widened copy see the same inputs, one of them non-finite
- **THEN** from the second finite input after the skip the copy's hindsight errors equal the live model's errors, and in the running module the shadows' buffers equal the live buffer after every report
