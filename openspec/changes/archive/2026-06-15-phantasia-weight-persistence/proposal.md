# Phantasia world-model weight persistence

## Why

The DreamerV3 world model starts from randomly-initialized parameters and
learns exclusively from the entity's own lived experience (waking observations
→ sleep-window replay training). Today those learned weights exist only in
process memory: every shutdown discards everything the world model has learned,
and every boot restarts imagination from scratch. For an entity whose boots are
ethically scarce, silently losing learned world-model state on every restart is
unacceptable — and it also makes the weights non-transferable, in tension with
CAL Article 4.2(b) (the entity's transferable cognitive state must survive
decommission/transfer).

The persistence seam already half-exists: `checkpoint.py` provides atomic,
encryption-aware save/load of opaque checkpoint bytes, and `serialize()`
already carries `checkpoint_path` metadata. What is missing is the
param-tree ⇄ bytes codec on the real backend, the load/save lifecycle wiring,
the config surface, and inclusion in the decommission backup bundle.

## What changes

- `DreamerV3WorldModel` gains `export_params() -> bytes` / `import_params(blob)`
  — an in-memory NPZ codec over the RSSM param tree with an embedded config
  header (`obs_dim`, RSSM dims, `latent_kind`, encoder version). Import
  fails closed on any config/shape mismatch.
- `Phantasia` gains `persist_weights` (shipped **false**) and
  `checkpoint_path` (default `state/phantasia/world_model.ckpt`):
  - load-on-initialize when the checkpoint file exists,
  - save after each successful sleep-window training pass,
  - save on shutdown,
  all through the existing `checkpoint.py` helpers (atomic replace; AES-256-GCM
  at rest when `[security.state_encryption]` is enabled).
- Honesty guards (no-pretend): `persist_weights = true` with a backend that
  cannot export real learned parameters (the `fake` EMA stub) is a
  **configuration error** at construction — persisting the stub would dress a
  fake up as learned state. An incompatible checkpoint at load is a **fatal
  error**, never a silent discard-and-reinit — throwing away learned weights
  without operator consent would destroy entity experience.
- Decommission backup (`capture_backup`) copies the checkpoint into the
  transfer bundle (same precedent as Hypnos adapters) and the restore notes
  cover it. Fork snapshots already carry `checkpoint_path` metadata.
- The zero-persistence boundary is **restated, not weakened**: the trajectory
  buffer and anything derived from raw sense data remain in-memory only,
  forever. Learned RSSM parameters are derived numeric weights, not sense
  data; persisting them is opt-in and encrypted at rest.

## Impact

- Affected specs: `phantasia` (1 modified, 1 added requirement),
  `welfare-gated-decommission` backup inventory (covered in the phantasia
  delta's backup scenario; the decommission code change is additive).
- Affected code: `kaine/modules/phantasia/world_model.py`, `module.py`,
  `config/kaine.toml`, `kaine/boot.py` (`make_phantasia`),
  `kaine/lifecycle/decommission.py`, `docs/modules/phantasia.md`.
- Shipped default is `persist_weights = false` — committed config stays
  guard-consistent (all-off / no behavior change until an operator opts in).
