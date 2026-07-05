## 1. Dependencies and packaging

- [ ] 1.1 Add `transformers>=4.40,<5` and `Pillow>=10,<12` to `pyproject.toml` `[project.dependencies]`
- [ ] 1.2 Add `kaine.modules.topos` to setuptools packages list
- [ ] 1.3 `pip install -e .[test]` in the venv

## 2. Encoder

- [ ] 2.1 Implement `kaine/modules/topos/encoder.py` with `Encoder` protocol and `DINOv2Encoder` default. Lazy `transformers`/`torch` import inside `load()`. Device via `select_device`. Frozen + eval-only at load time. `encode(image)` accepts PIL.Image, np.ndarray, or bytes; returns `list[float]` of length 384.

## 3. Change detection

- [ ] 3.1 Implement `kaine/modules/topos/change.py` with `ChangeDetector` protocol + `CosineChangeDetector` default. First call returns 0.0; subsequent calls compute `1 - cos_sim(prev, current)`. Tests confirm identical / orthogonal / anti-correlated edges.

## 4. Habituation

- [ ] 4.1 Implement `kaine/modules/topos/habituation.py` with `SceneHabituator` protocol + `RollingMeanHabituator` default. Rolling deque of recent embeddings, habituation = `1 / (1 + mean_pairwise_distance)`, clamped to `[0, 1]`.

## 5. Module

- [ ] 5.1 Implement `kaine/modules/topos/module.py` with `Topos(BaseModule)` — name="topos", DI for encoder / change / habituation, configurable salience, encoder_model_id surfaced in reports
- [ ] 5.2 `Topos.process_frame(image)` is the entry point: encode → change → habituation → publish → return entry id
- [ ] 5.3 `Topos.initialize` loads the encoder (which may download weights on first run); `shutdown` clears state
- [ ] 5.4 Update `kaine/modules/__init__.py` to export `Topos`

## 6. Config

- [ ] 6.1 Add `[topos]` block to `config/kaine.toml`
- [ ] 6.2 Add `topos = false` under `[modules]`

## 7. Tests

- [ ] 7.1 `tests/test_topos_change.py` — first frame zero, identical zero, orthogonal one, anti-correlated two
- [ ] 7.2 `tests/test_topos_habituation.py` — static scene → near 1.0, varied scene → low, window eviction
- [ ] 7.3 `tests/test_topos_encoder.py` — fake encoder roundtrip, parameter freeze assertion via mocked torch model, device propagation
- [ ] 7.4 `tests/test_topos_module.py` — fake encoder; one frame → one report; orthogonal frames → alert salience; encoder_model_id in payload; custom encoder substitution
- [ ] 7.5 `tests/test_topos_dinov2.py` — opt-in real-encoder test guarded by `KAINE_TOPOS_RUN_REAL_ENCODER=1`; asserts 384-dim output and frozen params

## 8. Documentation

- [ ] 8.1 Update `DEPENDENCIES.md` with transformers + Pillow rows
- [ ] 8.2 Optional: short note in SETUP.md that first Topos initialization will download ~85 MB from HuggingFace

## 9. Verification and tag

- [ ] 9.1 Full unit suite passes
- [ ] 9.2 `openspec validate topos --strict` clean
- [ ] 9.3 Commit, merge to main, archive change, drop branch
- [ ] 9.4 Tag `v0.2-perception` (closes Phase 2)
