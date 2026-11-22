## MODIFIED Requirements

### Requirement: Buffer summary serialized as statistical descriptor
When `serialize()` persists the visual buffer state, the serialized form SHALL
be a content-free descriptor holding exactly `n_frames` (the number of buffered
latents), `mean_norm` (the mean L2 norm of the buffered latents) and
`mean_variance` (the mean over dimensions of the per-dimension variance). It
SHALL NOT contain raw latent tensors, any per-dimension statistic of the latents
(a per-feature mean or variance included), or any other representation from
which the latents or the original video frames could be meaningfully
reconstructed.

#### Scenario: Serialized buffer contains only statistical summaries
- **WHEN** `Vision.serialize()` is called after 16 clips have been buffered
- **THEN** the buffer representation in the returned dict holds exactly
  `n_frames == 16`, `mean_norm` and `mean_variance`, each a single number, and no list

#### Scenario: An empty buffer
- **WHEN** `Vision.serialize()` is called before any clip has been buffered
- **THEN** the buffer representation holds `n_frames == 0` and zero for the other two fields
