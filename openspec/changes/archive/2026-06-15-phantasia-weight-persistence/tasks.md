# Tasks: phantasia-weight-persistence

## 1. World-model codec
- [ ] 1.1 `DreamerV3WorldModel.export_params() -> bytes`: in-memory NPZ over
      the flat `{group: {w, b}}` RSSM tree + JSON config header (obs_dim,
      deter/stoch/classes/hidden dims, latent_kind, encoder version).
- [ ] 1.2 `DreamerV3WorldModel.import_params(blob)`: parse, validate every
      header field and array shape against the running config; raise
      `CheckpointMismatchError` on any difference; install params only after
      full validation.
- [ ] 1.3 The `WorldModel` protocol documents the optional capability;
      `FakeWorldModel` deliberately does NOT implement it.

## 2. Module wiring
- [ ] 2.1 `Phantasia(persist_weights=False, checkpoint_path="state/phantasia/world_model.ckpt")`;
      construction raises `ValueError` when persist_weights is true and the
      world model lacks the export/import capability.
- [ ] 2.2 Load-on-initialize when the file exists (via
      `checkpoint.load_checkpoint`); mismatch propagates (fail closed).
- [ ] 2.3 Save after successful training pass + on shutdown (via
      `checkpoint.save_checkpoint`); save failures log.error honestly.
- [ ] 2.4 `serialize()` reports the active checkpoint path when persisting.

## 3. Config + boot
- [ ] 3.1 `config/kaine.toml`: `persist_weights = false`, `checkpoint_path`,
      comments stating the experience/weights persistence boundary.
- [ ] 3.2 `kaine/boot.py` `make_phantasia`: pass both keys through.

## 4. Decommission backup
- [ ] 4.1 `capture_backup` copies `state/phantasia/world_model.ckpt` into the
      bundle when present; inventory + restore notes updated.

## 5. Tests
- [ ] 5.1 Codec round-trip (jax importorskip): params equal, observe()
      behavior identical after import into a fresh model.
- [ ] 5.2 Import fails closed on dim/latent-kind/encoder-version mismatch.
- [ ] 5.3 persist_weights + fake backend → ValueError.
- [ ] 5.4 Module wiring with a persistable test double: save-on-shutdown,
      save-after-train, no-save-after-aborted-train, load-on-initialize.
- [ ] 5.5 Encrypted-at-rest round trip (KAINE_STATE_KEY).
- [ ] 5.6 Shipped config has persist_weights = false.
- [ ] 5.7 Decommission bundle includes the checkpoint.
- [ ] 5.8 Existing zero-persistence tests stay green unchanged.

## 6. Docs
- [ ] 6.1 `docs/modules/phantasia.md`: present-tense persistence section;
      zero-persistence note restated (buffer never; weights opt-in).
