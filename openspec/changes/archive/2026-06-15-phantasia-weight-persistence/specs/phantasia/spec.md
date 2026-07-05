## MODIFIED Requirements

### Requirement: In-memory-only training; zero-persistence
Phantasia SHALL perform all training in-memory and SHALL NOT serialize the
trajectory buffer or any raw-sense-derived data to disk. Any upstream
disk-serialization hooks from the vendored code SHALL be bypassed. Training
SHALL occur only when `training_enabled` is true and SHALL abort without
corrupting in-memory state if the loss becomes non-finite. No `.pt`, `.pkl`,
`.npy`, `.arrow`, or `.jsonl` files SHALL be written to `/tmp` or the project
directory during a training pass. Learned world-model parameters are NOT
sense data: they MAY be persisted, but only via the explicit, opt-in
weight-persistence requirement below — a training pass itself writes nothing.

#### Scenario: Training disabled skips the training pass
- **WHEN** maintenance runs with `training_enabled` false
- **THEN** the world-model weights are not updated

#### Scenario: No disk artifacts appear during training
- **WHEN** a training pass completes successfully
- **THEN** no new `.pt`, `.pkl`, `.npy`, `.arrow`, or `.jsonl` files exist in
  `/tmp` or the project directory that were not present before the pass

#### Scenario: No actor-critic params in optimizer state
- **WHEN** the optimizer state is inspected after a training pass
- **THEN** no actor or critic parameter tensors appear in the optimizer state

#### Scenario: NaN loss aborts training without corruption
- **WHEN** the training loss becomes non-finite
- **THEN** the training pass aborts and in-memory model state is not corrupted

#### Scenario: Trajectory buffer is never serialized
- **WHEN** `serialize()` is called or a weight checkpoint is written
- **THEN** the trajectory buffer contents appear in neither the serialized
  state nor the checkpoint bytes

## ADDED Requirements

### Requirement: Opt-in persistence of learned world-model weights
Phantasia SHALL persist learned world-model parameters across restarts when
`[phantasia].persist_weights` is true, and SHALL ship with
`persist_weights = false`. When enabled, Phantasia SHALL load the checkpoint
at `checkpoint_path` during initialization if it exists, SHALL save after
each successful (non-aborted, at-least-one-step) training pass, and SHALL
save on shutdown. Checkpoint writes SHALL be atomic
(write-temp-then-replace) and SHALL be encrypted at rest whenever
`[security.state_encryption]` is enabled. The checkpoint SHALL embed the
world-model configuration (observation dimension, RSSM dimensions, latent
kind, encoder version); loading a checkpoint whose configuration does not
match the running model SHALL fail closed with an operator-actionable error
— never a silent discard-and-reinitialize. Enabling `persist_weights` with a
backend that cannot export real learned parameters (the `fake` EMA stub)
SHALL be a configuration error at construction. The decommission backup
bundle SHALL include the checkpoint file when one exists, as transferable
cognitive state per CAL Article 4.2(b).

#### Scenario: Weights survive a restart
- **WHEN** `persist_weights` is true, a training pass completes, the module
  shuts down, and a new Phantasia instance initializes with the same
  `checkpoint_path`
- **THEN** the new instance's world model carries the saved parameters
  instead of a fresh random initialization

#### Scenario: Save after successful sleep training
- **WHEN** `persist_weights` is true and a sleep-window training pass
  completes with at least one step and without abort
- **THEN** the checkpoint at `checkpoint_path` is (re)written atomically

#### Scenario: Aborted training does not overwrite the checkpoint
- **WHEN** a training pass aborts (non-finite loss)
- **THEN** the existing checkpoint file is left unchanged

#### Scenario: Encrypted at rest
- **WHEN** `[security.state_encryption]` is enabled and a checkpoint is saved
- **THEN** the bytes on disk are an AES-256-GCM envelope, and loading
  decrypts them transparently

#### Scenario: Incompatible checkpoint fails closed
- **WHEN** the checkpoint's embedded configuration (e.g. `obs_dim` after an
  encoder version bump) does not match the running world model
- **THEN** initialization raises an operator-actionable error naming the
  mismatch and the checkpoint file is not modified

#### Scenario: Fake backend cannot persist
- **WHEN** Phantasia is constructed with `persist_weights = true` and
  `backend = "fake"`
- **THEN** construction raises a configuration error (the EMA stub has no
  real learned parameters to persist)

#### Scenario: Shipped default is off
- **WHEN** the committed `config/kaine.toml` is inspected
- **THEN** `[phantasia].persist_weights` is false

#### Scenario: Decommission backup includes the checkpoint
- **WHEN** `capture_backup` runs and `state/phantasia/world_model.ckpt`
  exists
- **THEN** the bundle contains the checkpoint and the manifest inventory and
  restore notes reference it
