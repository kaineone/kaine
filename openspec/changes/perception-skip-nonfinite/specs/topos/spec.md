## MODIFIED Requirements

### Requirement: Vision publishes topos.report for each processed frame
Vision SHALL maintain a bounded, RAM-only ring buffer of the most recent frames of
size `clip_len`. Vision SHALL publish a `topos.report` event to its `topos.out`
stream when the ring buffer is full AND a clip latent is produced on the clip
cadence (see the strided-clip requirement) — NOT once per incoming frame. Before
the ring buffer first fills, Vision SHALL publish no `topos.report`. Each published
event SHALL carry `latent` (list of floats — the pooled clip embedding, or null
when the embedding holds a non-finite value), `change_score` (float `>= 0`),
`habituation_score` (float in `[0.0, 1.0]`, or null when the first finite
embedding has not yet been seen), `encoder_model_id` (string), and
`prediction_error` (float, or null when the report has no defined error). With
foveation on, `peripheral` and `foveal` SHALL likewise be null when they hold a
non-finite value. Salience SHALL be
elevated when `change_score` exceeds the configured alert threshold (or, when the
forward model is enabled, when the normalized prediction error is surprising).

#### Scenario: No report until the buffer fills
- **WHEN** fewer than `clip_len` frames have been processed after initialization
- **THEN** no `topos.report` event has been published

#### Scenario: A produced clip latent yields one report
- **WHEN** the ring buffer is full and a clip latent is produced on the cadence
- **THEN** exactly one `topos.report` event appears on `topos.out` carrying the
  768-dim `latent`, `change_score`, `habituation_score`, `encoder_model_id`, and
  `prediction_error`

#### Scenario: Large change elevates salience
- **WHEN** two produced clip latents are orthogonal and the change exceeds the
  configured alert threshold
- **THEN** the second event's salience equals the configured alert salience

#### Scenario: A non-finite embedding is published as null
- **WHEN** the produced clip latent contains a non-finite value
- **THEN** the report carries `latent` and `prediction_error` as null and no non-finite number
