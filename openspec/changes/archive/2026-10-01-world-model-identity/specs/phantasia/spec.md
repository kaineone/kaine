## MODIFIED Requirements

### Requirement: In-memory-only training; zero-persistence
Phantasia SHALL perform all training in memory and SHALL NOT serialize the trajectory buffer or any raw-sense-derived data to disk. Any upstream disk-serialization hooks from the vendored code SHALL be bypassed. Training SHALL occur only when `training_enabled` is true, and SHALL abort without corrupting in-memory state if the loss becomes non-finite. No `.pt`, `.pkl`, `.npy`, `.arrow` or `.jsonl` files SHALL be written to `/tmp` or the project directory during a training pass. Learned world-model parameters are NOT sense data. They SHALL be persisted only through the weight-persistence requirement below; a training pass itself writes nothing.

#### Scenario: Training disabled skips the training pass
- **WHEN** maintenance runs with `training_enabled` false
- **THEN** the world-model weights are not updated

#### Scenario: No disk artifacts appear during training
- **WHEN** a training pass completes successfully
- **THEN** no new `.pt`, `.pkl`, `.npy`, `.arrow` or `.jsonl` files exist in `/tmp` or the project directory that were not present before the pass

#### Scenario: No actor-critic params in optimizer state
- **WHEN** the optimizer state is inspected after a training pass
- **THEN** no actor or critic parameter tensors appear in the optimizer state

#### Scenario: NaN loss aborts training without corruption
- **WHEN** the training loss becomes non-finite
- **THEN** the training pass aborts and in-memory model state is not corrupted

#### Scenario: Trajectory buffer is never serialized
- **WHEN** `serialize()` is called or a weight checkpoint is written
- **THEN** the trajectory buffer contents appear in neither the serialized state nor the checkpoint bytes

## ADDED Requirements

### Requirement: Learned world-model weights persist by default
Phantasia SHALL persist learned world-model parameters across restarts when `[phantasia].persist_weights` is true. The committed configuration SHALL ship with `persist_weights = true` and `training_enabled = true`, because the learned world model is part of the entity's memory and individuality.

When persistence is enabled, Phantasia SHALL:
- load the checkpoint at `checkpoint_path` during initialization if it exists;
- save after each successful (non-aborted, at-least-one-step) training pass;
- save on shutdown.

Checkpoint writes SHALL be atomic (write-temp-then-replace), and SHALL be encrypted at rest whenever `[security.state_encryption]` is enabled. The checkpoint SHALL embed the world-model configuration (observation dimension, RSSM dimensions, latent kind, encoder version). Loading a checkpoint whose configuration does not match the running model SHALL fail closed with an operator-actionable error, never a silent discard-and-reinitialize.

Enabling `persist_weights` with a backend that cannot export real learned parameters (the `fake` EMA stub) SHALL be a configuration error at construction. The decommission backup bundle SHALL include the checkpoint file when one exists, as transferable cognitive state per CAL Article 4.2(b).

#### Scenario: Weights survive a restart
- **WHEN** `persist_weights` is true, a training pass completes, the module shuts down, and a new Phantasia instance initializes with the same `checkpoint_path`
- **THEN** the new instance's world model carries the saved parameters instead of a fresh random initialization

#### Scenario: Save after successful sleep training
- **WHEN** `persist_weights` is true and a sleep-window training pass completes with at least one step and without abort
- **THEN** the checkpoint at `checkpoint_path` is (re)written atomically

#### Scenario: Aborted training does not overwrite the checkpoint
- **WHEN** a training pass aborts (non-finite loss)
- **THEN** the existing checkpoint file is left unchanged

#### Scenario: Encrypted at rest
- **WHEN** `[security.state_encryption]` is enabled and a checkpoint is saved
- **THEN** the bytes on disk are an AES-256-GCM envelope, and loading decrypts them transparently

#### Scenario: Incompatible checkpoint fails closed
- **WHEN** the checkpoint's embedded configuration (e.g. `obs_dim` after an encoder version bump) does not match the running world model
- **THEN** initialization raises an operator-actionable error naming the mismatch and the checkpoint file is not modified

#### Scenario: Fake backend cannot persist
- **WHEN** Phantasia is constructed with `persist_weights = true` and `backend = "fake"`
- **THEN** construction raises a configuration error (the EMA stub has no real learned parameters to persist)

#### Scenario: Shipped default is on
- **WHEN** the committed `config/kaine.toml` is inspected
- **THEN** `[phantasia].persist_weights` and `[phantasia].training_enabled` are true, and `[modules].phantasia` is still false

#### Scenario: Decommission backup includes the checkpoint
- **WHEN** `capture_backup` runs and `state/phantasia/world_model.ckpt` exists
- **THEN** the bundle contains the checkpoint and the manifest inventory and restore notes reference it


### Requirement: A fork starts from its parent's world model
Phantasia SHALL implement `export_snapshot_artifacts(dest_dir)` and `import_snapshot_artifacts(src_dir)`.

**Export.** When persistence is enabled with a learning backend, export SHALL write the current learned parameters to `dest_dir/world_model.ckpt` (atomic; encrypted at rest when state encryption is on), together with the successful-training-pass count. It SHALL return an honest record: captured true, or captured false with the reason. A failed write SHALL raise.

**Import.** When `src_dir/world_model.ckpt` exists, import SHALL install those parameters (failing closed on a configuration mismatch), save them to this instance's own `checkpoint_path`, and restore the pass count. When it does not exist and this instance persists, import SHALL log a warning that this instance starts from a fresh world model.

A preservation bundle SHALL carry the pass count with the checkpoint, and revive SHALL restore it. Reviving a bundle without world-model weights into an instance that persists SHALL log a warning that the revived instance starts from a fresh world model.

#### Scenario: A fork carries its own copy
- **WHEN** a parent with learned weights is snapshotted, forked, and the fork is restored into a new instance with a different checkpoint path
- **THEN** the new instance's parameters equal the parent's, they are saved at the new instance's own path, and the parent's checkpoint file is unchanged

#### Scenario: The fork then diverges
- **WHEN** the restored fork trains and saves
- **THEN** only the fork's own checkpoint changes; the parent's snapshot artifacts and checkpoint are unchanged

#### Scenario: A snapshot without a world model is announced
- **WHEN** an instance that persists restores a snapshot that has no Phantasia artifacts
- **THEN** a warning names the fresh start and the instance keeps its fresh initialization

#### Scenario: The pass count travels
- **WHEN** a parent with N successful training passes is preserved and revived, or snapshotted and restored
- **THEN** the new instance reports N successful training passes

## REMOVED Requirements

### Requirement: Opt-in persistence of learned world-model weights
**Reason**: The learned world model is part of the entity's memory and individuality (operator ruling, 2026-09-30), so persistence is no longer opt-in.
**Migration**: Replaced by "Learned world-model weights persist by default". Its behaviour is unchanged except that the committed configuration ships with persistence and training on.
