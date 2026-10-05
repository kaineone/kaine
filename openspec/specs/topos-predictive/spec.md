# topos-predictive Specification

## Purpose
This capability gives Topos a visual forward model that predicts the next latent from the current latent and recurrent visual buffer, driving salience from prediction error. Topos adapts the model online with a single gradient step per clip latent, summarizes the buffer as a statistical descriptor for serialization, and binds the latent dimension to the active encoder.

## Requirements

### Requirement: Visual forward model predicts next latent
Topos SHALL maintain a forward model that predicts the next visual latent from the
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
distinct from and does not affect Phantasia's DreamerV3 world model, which predicts
the fused whole-workspace state; the two predictors SHALL NOT be conflated.

#### Scenario: Encoder stays frozen
- **WHEN** the forward model takes an online update step
- **THEN** no parameter of the visual encoder is modified

#### Scenario: Forward-model dimension follows the encoder
- **WHEN** the default 768-dim temporally-native encoder is active
- **THEN** the forward model's input and output latent dimension is 768, taken
  from the encoder rather than a hardcoded 384

#### Scenario: Mismatched checkpoint is discarded, not loaded
- **WHEN** `Topos.deserialize` receives a forward-model checkpoint whose tensor
  shapes do not match the running encoder's `latent_dim`
- **THEN** the checkpoint's forward-model weights are discarded with a warning and
  the model continues to learn online, without raising a shape error

#### Scenario: Buffer is bounded
- **WHEN** more clip latents than `visual_buffer_size` have been observed
- **THEN** the recurrent visual buffer holds at most `visual_buffer_size` latents

### Requirement: Salience is driven by prediction error
Topos event salience SHALL be driven by the visual prediction error (the
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
- **WHEN** Topos publishes a report
- **THEN** the payload still contains `change_score` and `habituation_score`

#### Scenario: A perceptual discontinuity alerts

- **WHEN** the perceptual stream contains a change whose prediction error is at
  least k times the module's rolling-window baseline (e.g. a scene cut)
- **THEN** the emitted `topos.report` carries the alert salience, not the baseline

#### Scenario: A steady stream stays at baseline

- **WHEN** the perceptual stream is steady and well-predicted (prediction error near
  the rolling baseline)
- **THEN** the emitted `topos.report` carries the baseline salience

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
- **WHEN** `Topos.serialize()` is called
- **THEN** the buffer representation in the returned dict contains only numeric
  statistical summary fields (mean, variance, or equivalent) and no raw latent
  tensors
