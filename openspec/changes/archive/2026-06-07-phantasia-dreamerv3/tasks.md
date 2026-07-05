## 1. Vendor danijar/dreamerv3

- [x] 1.1 Clone danijar/dreamerv3 at a stable commit; copy RSSM-relevant source into `external/dreamerv3/`; write `external/dreamerv3/UPSTREAM` with the commit hash and SPDX MIT notice; exclude actor/critic/return heads
- [x] 1.2 Add `jax[cpu]`, `chex`, `einops` (and other required transitive deps) to the `[worldmodel]` optional extra in `pyproject.toml`

## 2. World model wrapper

- [x] 2.1 `kaine/modules/phantasia/world_model.py` — `WorldModel` protocol (observe, imagine, train) wrapping the vendored RSSM core (recurrent + stochastic latent transition, encoder, decoder, imagination rollout); actor/critic/return heads excluded
- [x] 2.2 `FakeWorldModel` in the same file — zero-dep stub that satisfies the protocol; used by all tests
- [x] 2.3 NaN-loss guard: abort training pass without corrupting in-memory state

## 3. Observation encoder

- [x] 3.1 `kaine/modules/phantasia/encoder.py` — `WorkspaceSnapshot` → fixed-width observation vector (salience-weighted coalition + affect summary + inhibition); exposes a `VERSION` string; contains no raw audio/image bytes

## 4. Module

- [x] 4.1 `kaine/modules/phantasia/module.py` — `Phantasia(BaseModule)`; bounded in-memory waking trajectory ring buffer (never serialized to disk)
- [x] 4.2 Waking: predict next latent, publish `phantasia.world_error` (salience-only; no scenario content)
- [x] 4.3 Offline: on `mnemos.replay` cue, roll out imagined trajectories and publish `phantasia.scenario`; re-inject scenarios into the workspace broadcast so Nous/Thymos/Eidolon process them via `on_workspace`
- [x] 4.4 Training: in-memory only, gated by `training_enabled`; bypass any upstream disk-serialization hooks; no `.pt`/`.pkl`/`.npy`/`.arrow`/`.jsonl` written to `/tmp` or project dir

## 5. Boot + config

- [x] 5.1 `make_phantasia` factory + `SIMPLE_FACTORIES` registration; `serialize()`/`deserialize()` for world-model checkpoint path (checkpoint itself stays in-memory during a run)
- [x] 5.2 `[phantasia]` config: `backend`, `training_enabled`, `training_device`, `trajectory_buffer_size`, `rollout_horizon`, `salience`; `[modules].phantasia = false`
- [x] 5.3 Export `Phantasia`

## 6. FaithfulRenderer templates

- [x] 6.1 Register a `FaithfulRenderer` template for `(phantasia, phantasia.world_error)` — renders source, type, and salience value as human-readable plain text
- [x] 6.2 Register a `FaithfulRenderer` template for `(phantasia, phantasia.scenario)` — renders source, type, and a summary of the imagined trajectory

## 7. Tests

- [x] 7.1 `tests/test_phantasia_encoder.py` — snapshot → fixed-width vector; no raw sense data; VERSION stamp present
- [x] 7.2 `tests/test_phantasia_world_model.py` — FakeWorldModel satisfies protocol without JAX; rollout shape; NaN-loss aborts without corruption; no actor/critic params in optimizer state after training
- [x] 7.3 `tests/test_phantasia_module.py` (fakeredis) — waking emits `phantasia.world_error` (no scenario content); `mnemos.replay` cue emits `phantasia.scenario`; scenario is re-injected into workspace broadcast; trajectory buffer bounded; no raw sense data on the bus
- [x] 7.4 `tests/test_phantasia_zero_persistence.py` — assert no new `.pt`/`.pkl`/`.npy`/`.arrow`/`.jsonl` files appear in `/tmp` or project dir during a training pass
- [x] 7.5 `tests/test_phantasia_faithful_renderer.py` — `phantasia.world_error` and `phantasia.scenario` render via named templates (not fallback); no banned phrases
- [x] 7.6 `tests/test_boot_wiring.py` — SIMPLE_FACTORIES includes `phantasia`

## 8. Verification

- [x] 8.1 Full unit suite green (no `[worldmodel]` extra needed — FakeWorldModel covers CI)
- [x] 8.2 `openspec validate phantasia-dreamerv3 --strict` clean
- [x] 8.3 Commit (Kaine.One), branch-per-change, merge, archive
