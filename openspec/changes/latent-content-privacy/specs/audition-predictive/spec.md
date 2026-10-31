## MODIFIED Requirements

### Requirement: Buffer summary is a statistical descriptor, not raw latents
When `serialize()` persists the auditory buffer state or the acoustic buffer
state, each serialized form SHALL be a content-free descriptor holding exactly
`n_frames`, `mean_norm` (the mean L2 norm of the buffered vectors) and
`mean_variance` (the mean over dimensions of the per-dimension variance). It
SHALL NOT contain raw audio bytes, raw waveform latents, any per-dimension
statistic of the buffered vectors, or any representation from which the
original audio signal or its embeddings could be reconstructed.

#### Scenario: Serialized buffer contains no raw audio
- **WHEN** `Audition.serialize()` is called
- **THEN** the returned dict's buffer representations contain only the three
  scalar fields and no `bytes` values

#### Scenario: The acoustic summary holds no per-dimension mean
- **WHEN** `Audition.serialize()` is called after the acoustic buffer holds 16 embeddings
- **THEN** the acoustic buffer summary holds `n_frames == 16`, `mean_norm` and
  `mean_variance`, and no list
