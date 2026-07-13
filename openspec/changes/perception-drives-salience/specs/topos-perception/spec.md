## MODIFIED Requirements

### Requirement: Perceptual salience is stimulus-driven prediction error

Topos SHALL derive a report's salience from forward-model prediction error against
the perceptual stream, using a criterion that is **relative to the module's own
rolling baseline** rather than an absolute constant, so the alert condition is
independent of the encoder's embedding scale (InternVideo-Next clip latent,
foveal-gist, or DINOv2). A perceptual discontinuity SHALL raise salience above
baseline; a steady, well-predicted stream SHALL remain at baseline. Salience MUST
NOT be a constant independent of the stimulus.

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
