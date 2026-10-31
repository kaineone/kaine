## MODIFIED Requirements

### Requirement: Observations are workspace summaries, not raw senses
The world model module SHALL encode each `WorkspaceSnapshot` to a fixed-width observation
vector (salience-weighted coalition + affect summary + inhibition flag) using a
versioned encoder. When `[world_model].content_observation` is true, the observation SHALL
also carry a content part from the declared content source. No raw audio or image bytes
SHALL appear in the observation vector or the trajectory buffer.

#### Scenario: Observation vector contains no raw sense data
- **WHEN** the world model module encodes a tick for its world model
- **THEN** the observation vector is derived from the workspace snapshot and
  contains no raw audio or image bytes

#### Scenario: Encoder version stamp is present
- **WHEN** the encoder is inspected
- **THEN** it exposes a non-empty `VERSION` string

#### Scenario: Content part present when enabled
- **WHEN** `content_observation` is true and the snapshot's accessed members include a vision report
- **THEN** the observation's content part is non-zero and its width equals the configured content width

## ADDED Requirements

### Requirement: The content source is declared and recorded

The content part SHALL come from the accessed content code of `latent-workspace-content-level` when that capability is enabled, and otherwise from an online projection of the accessed perceptual members' latents and interoception's readings, fitted in sleep and frozen while awake. The source SHALL be recorded in the checkpoint and on every `world_model.*` event.

#### Scenario: Source disclosed

- **WHEN** a `world_model.content_error` event is published
- **THEN** its payload names the content source

### Requirement: The waking error has a summary part and a content part

The world model module SHALL publish the summary-part error as `world_model.world_error` with its current meaning, and the content-part error as `world_model.content_error`, each scaled by the precision of its own recent errors. Neither event SHALL carry a predicted or observed content vector.

#### Scenario: Content error carries no vector

- **WHEN** a `world_model.content_error` event is inspected
- **THEN** its payload holds scalars and identifiers only

### Requirement: Adding the content part preserves a preserved model's predictions

Migrating a checkpoint without a content part SHALL add zero-initialised input and output weights for it, so the migrated model's summary-part predictions equal the original's. Until the content decoder has completed `content_warmup_passes` sleep passes, `world_model.content_error` SHALL be recorded but SHALL NOT be published as a workspace candidate.

#### Scenario: Migration is lossless for the summary

- **WHEN** a preserved checkpoint is migrated and both models run on the same recorded trajectory
- **THEN** their summary-part predictions are identical on every step

#### Scenario: No content candidates before warm-up

- **WHEN** a migrated model has completed fewer than `content_warmup_passes` passes
- **THEN** no `world_model.content_error` reaches the workspace
