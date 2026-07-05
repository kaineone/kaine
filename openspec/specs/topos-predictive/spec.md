# topos-predictive Specification

## Purpose
TBD - created by archiving change topos-forward-model. Update Purpose after archive.
## Requirements
### Requirement: Visual forward model predicts next latent
Topos SHALL maintain a forward model that predicts the next DINOv2 latent from
the current latent and a recurrent visual buffer, and SHALL adapt it online with
a single small gradient step per frame, skipping any non-finite update. The
DINOv2 encoder SHALL remain frozen (no gradients flow into it).

#### Scenario: Encoder stays frozen
- **WHEN** the forward model takes an online update step
- **THEN** no parameter of the DINOv2 encoder is modified

#### Scenario: Buffer is bounded
- **WHEN** more frames than `visual_buffer_size` have been observed
- **THEN** the recurrent visual buffer holds at most `visual_buffer_size` latents

### Requirement: Salience is driven by prediction error
Topos event salience SHALL be driven by the visual prediction error (the
magnitude of the predicted-minus-actual latent), such that a predictable change
yields lower salience than an equally large but unpredicted change. The legacy
`change_score` and `habituation_score` SHALL remain on the event payload for
diagnostics.

#### Scenario: Predictable motion is less salient than surprise
- **WHEN** a smoothly predictable latent trajectory and an abrupt unpredicted
  latent jump produce equal raw cosine change
- **THEN** the unpredicted jump yields strictly higher event salience

#### Scenario: Diagnostics fields retained
- **WHEN** Topos publishes a report
- **THEN** the payload still contains `change_score` and `habituation_score`

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

