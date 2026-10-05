## MODIFIED Requirements

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
