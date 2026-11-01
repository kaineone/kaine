## MODIFIED Requirements

### Requirement: Buffer summary is a statistical descriptor, not raw latents
When `serialize()` persists the auditory buffer state or the acoustic buffer
state, each serialized form SHALL be a content-free descriptor holding exactly
`n_frames` (the number of buffered vectors), `mean_norm` (the mean L2 norm of
the buffered vectors) and `mean_variance` (the mean over dimensions of the
per-dimension variance). It SHALL NOT contain raw audio bytes, raw waveform
latents, any per-dimension statistic of the buffered vectors, or any
representation from which the original audio signal or its embeddings could be
reconstructed.

#### Scenario: Serialized buffer contains no raw audio
- **WHEN** `Audition.serialize()` is called
- **THEN** the returned dict's buffer representations contain only the three
  scalar fields and no `bytes` values

#### Scenario: The acoustic summary holds no per-dimension mean
- **WHEN** `Audition.serialize()` is called after the acoustic buffer holds 16 embeddings
- **THEN** the acoustic buffer summary holds `n_frames == 16`, `mean_norm` and
  `mean_variance`, and no list

## ADDED Requirements

### Requirement: Carried acoustic summaries are rewritten on restore
When `Audition.deserialize()` restores an acoustic forward-model entry for an encoder that is not running and carries it forward, it SHALL rewrite that entry's `buffer_summary` into the three-scalar form before keeping it. An entry whose summary holds per-dimension statistics SHALL become `n_frames` with the old count and zero for `mean_norm` and `mean_variance`.

#### Scenario: An old-format carried entry
- **WHEN** a snapshot holds an acoustic entry for a non-running encoder whose `buffer_summary` has per-feature `mean` and `variance` lists, and the module is restored and serialized
- **THEN** the serialized carried entry's `buffer_summary` holds only `n_frames`, `mean_norm` and `mean_variance`, and no list
