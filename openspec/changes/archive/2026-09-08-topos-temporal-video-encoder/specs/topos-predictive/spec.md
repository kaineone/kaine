## MODIFIED Requirements

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
