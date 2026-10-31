## 0. Gates and coordination

- [ ] 0.1 Gate: after the module-addition study; nothing here changes an image a running study uses.
- [ ] 0.2 Read the result of `latent-workspace-content-level`'s offline decodability check, if it has run, and choose D1's default source.
- [ ] 0.3 Agree the imagination reply's fields with the agency workstream's planning change before task 2.1; record the agreed contract in both changes.
- [ ] 0.4 Note in `world-model-action-outcomes` that its action vocabulary is what `world_model.imagine.request` policies use.

## 1. Content observation and error

- [ ] 1.1 Encoder version with the content part; online projection fitted in sleep and frozen while awake; the declared content-code source. Tests: extend `tests/test_world_model_encoder.py` (content part present; no raw bytes; version bumped).
- [ ] 1.2 Both engines predict the content part; parity between JAX and NumPy. Tests: extend `tests/test_world_model_numpy_engine.py` and `tests/test_world_model_backend.py`.
- [ ] 1.3 Two-part error, precision-scaled; `world_model.content_error` with scalars only; the warm-up rule. Tests: extend `tests/test_world_model_module.py`.
- [ ] 1.4 Checkpoint migration with zero-initialised weights. Tests: extend `tests/test_world_model_persistence.py` and `tests/test_world_model_identity.py` (migrated model predicts the summary identically on a recorded trajectory; forks copy the migrated model).
- [ ] 1.5 Privacy: content-part vectors never in diagnostics or logs; buffer stays in memory. Tests: extend `tests/test_world_model_zero_persistence.py` and `tests/test_privacy_strip_vectors.py`.
- [ ] 1.6 Offline validation on recorded waking trajectories: content-part prediction above a shuffled-time control. Record under `docs/records/validation/world-model-content/`.

## 2. Imagination interface

- [ ] 2.1 Request and reply events, bounds, timeout, the map registration protocol (declared under `module-control-interfaces`). Tests: `tests/test_world_model_imagination.py` (prediction-only request, over-bound request, unregistered map, late rollout not published).
- [ ] 2.2 Research-log taxonomy entry for replies (ids, counts, timing only). Test in the research-event observer suite.

## 3. Validation and docs

- [ ] 3.1 New individuation reference procedure for entities whose world model gains content; one supervised validation boot after a green pre-boot dry run.
- [ ] 3.2 Docs: `docs/09-modules/world-model.md`; paper revision note for the §4 row and §10.
- [ ] 3.3 `openspec validate world-model-content-prediction --strict`.
