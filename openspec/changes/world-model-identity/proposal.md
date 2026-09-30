## Why

The operator ruled (2026-09-30): "the world model of an entity is a core part of its memory and divergent personality from other forks … no two entities who've had different experiences in the world will have the same learned weights to their world model. so that should stay with an entity across reboots, and be the starting world model of any later forks for that entity."

The code does not meet that rule:

1. **Off by default.** `config/kaine.toml` ships `[phantasia].persist_weights = false` and `training_enabled = false`, and the constructor defaults match. Out of the box, an entity's world model neither learns nor survives a reboot. The change that added persistence (`2026-06-15-phantasia-weight-persistence`) argued for it ("silently losing learned world-model state on every restart is unacceptable"). It shipped off only to keep the committed configuration unchanged.
2. **Forks never carry the world model.** `ForkManager.snapshot` stores each module's `serialize()`, and Phantasia serializes only metadata. A fork restored in the same data root reads and writes its **parent's** checkpoint file. One restored elsewhere starts from a fresh world model without saying so.
3. **Merge picks by accident.** Phantasia has no merge strategy, so the metadata is merged last-write-wins, and the weights not at all.
4. **Silent revive.** Reviving a bundle that has no world model into an instance that persists gives a fresh world model with no warning.
5. **The pass count is not bundled.** The consolidation pass count (the checkpoint's sidecar), which the maturation gate reads, is not part of the preservation bundle.

## What Changes

- **Shipped defaults:** `[phantasia].persist_weights = true` and `training_enabled = true`.
  - Training stays in memory, CPU by default, with the existing NaN guard.
  - Phantasia itself stays off in the shipped `[modules]`, so the committed config still boots no module.
  - The `fake` backend with persistence remains a configuration error.
- **Module artifacts in snapshots.** `ForkManager` supports two optional module hooks, `export_snapshot_artifacts(dest_dir)` and `import_snapshot_artifacts(src_dir)`. A snapshot keeps each module's artifacts in `<snapshot>/artifacts/<module>/`, next to `snapshot.json`, with the same 0700/0600 permissions and encryption at rest.
  - **snapshot:** exports every module's artifacts. An export that fails fails the snapshot, and nothing is saved. A snapshot never claims completeness while omitting part of the individual.
  - **fork:** copies the parent's artifacts, except for shed modules, into the child's own snapshot directory. Each fork owns its own copy, never a shared file.
  - **restore:** imports each module's artifacts into that instance. Phantasia installs the weights and saves them to its own configured checkpoint path. A missing world model is logged as a warning naming the fresh start.
  - **merge:** refuses when both parents carry a world model, unless the caller names which parent's world model continues (`world_model_from="a"` or `"b"`). Two divergent world models cannot be averaged meaningfully, the same rule the merge follows for trained voice adapters. The choice is recorded in the merged snapshot's metadata.
- **Phantasia implements the hooks.** It exports the encrypted checkpoint and the pass-count sidecar, and imports both.
- **Preservation** bundles the pass-count sidecar with the checkpoint, and revive restores it. Reviving a bundle without a world model into an instance that persists logs a warning naming the fresh start.

## Capabilities

### Modified Capabilities
- `phantasia`: persistence and training are on by default; a fork starts from its parent's world model; the pass count travels with the weights.
- `entity-preservation`: fork and merge snapshots carry module artifacts; merge refuses to pick a world model by accident.

## Impact

- **Code:** `kaine/lifecycle/manager.py`, `kaine/lifecycle/snapshot.py` (artifact directory helper), `kaine/modules/phantasia/module.py`, `kaine/lifecycle/preservation.py`, `config/kaine.toml`.
- **Tests:** the shipped-default guard `test_shipped_config_persist_weights_off` becomes an "on" guard. New fork, restore and merge tests. Preservation sidecar tests.
- **Not in this change:** the off-host temporary-being job (`kaine/distributed/fork_being.py`) references a fork snapshot by id, and its executor is not built yet. When it is, it must ship the whole snapshot directory, artifacts included. This proposal records that requirement for it.
- **Unchanged:** the trajectory buffer is never persisted (zero-persistence), a training pass writes nothing to disk, and encryption, atomic replace and fail-closed mismatch handling are unchanged.
- **Docs:** `docs/modules/phantasia.md`, `docs/configuration.md`, and the fork and merge docs.
