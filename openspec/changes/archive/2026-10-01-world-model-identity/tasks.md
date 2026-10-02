## 1. Defaults
- [x] 1.1 `config/kaine.toml` `[phantasia]`: `persist_weights = true` and `training_enabled = true`, with comments. The world model is part of the entity's memory and individuality, and training runs in memory during Hypnos on the configured device. `[modules].phantasia` stays false.
- [x] 1.2 Turn the shipped-default guard test into an "on" guard. Keep the guard that `[modules]` ships all-off.

## 2. Snapshot artifacts
- [x] 2.1 `kaine/lifecycle/snapshot.py`: `artifacts_dir(root, snapshot_id, module_name)` builds its path through `snapshot_dir` (id validation and containment) and refuses a module name with a path separator or `..`. Add a copy helper that preserves 0700/0600.
- [x] 2.2 `kaine/lifecycle/manager.py`:
  - `snapshot` runs the export hooks before saving and records `metadata["artifacts"]`. It removes the snapshot directory and re-raises if a hook raises.
  - `fork` copies the parent's artifacts, except for shed modules.
  - `restore` calls the import hooks.
  - `merge` gains `world_model_from: str | None = None`, refuses when both parents carry Phantasia artifacts and no choice is given, copies artifacts per module, and records `metadata["artifact_sources"]`.

## 3. Phantasia
- [x] 3.1 `export_snapshot_artifacts` and `import_snapshot_artifacts`, as in the spec. Reuse `save_checkpoint`/`load_checkpoint` and the existing pass-count sidecar logic. The import fails closed on a mismatch, saves to this instance's own path, and warns on a fresh start.
- [x] 3.2 Preservation: bundle the pass-count sidecar with the checkpoint, and restore it on revive. Warn when a bundle without weights is revived into an instance that persists.

## 4. Tests
- [x] 4.1 Fork and restore with real learned parameters (the NumPy engine):
  - the child's parameters equal the parent's;
  - they are saved at the child's own path;
  - the parent's file is unchanged;
  - after the child trains, the parent's snapshot artifacts are unchanged.
- [x] 4.2 Remaining artifact behaviour:
  - two forks hold independent copies;
  - a shed module is not copied;
  - a failed export leaves no snapshot directory;
  - a missing artifact produces a warning and a fresh start;
  - a mismatched artifact fails closed on restore.
- [x] 4.3 Merge: refusal without a choice when both parents carry world models; the named choice is copied and recorded; one parent with a world model merges without a choice.
- [x] 4.4 The pass count survives preserve and revive, and snapshot and restore. Revive without weights into a persisting instance warns.
- [x] 4.5 The existing Phantasia, persistence, preservation, revive, fork and merge suites pass. The shipped-default change is reflected, and the study overlay tests are unaffected.

## 5. Docs
- [x] 5.1 `docs/modules/phantasia.md`, `docs/configuration.md` and the fork and merge docs: the world model persists by default, travels with forks, and merge requires a choice. The note that the off-host forked-being executor must ship the whole snapshot directory.
