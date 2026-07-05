## 1. Package skeleton

- [x] 1.1 Create `kaine/modules/chronos/__init__.py` exporting the public surface
- [x] 1.2 Add `kaine.modules.chronos` to `pyproject.toml` setuptools packages

## 2. Featurizer

- [x] 2.1 Implement `kaine/modules/chronos/featurizer.py` with `SnapshotFeaturizer` producing a fixed 24-dim float vector from a `WorkspaceSnapshot`; pure-Python, no torch
- [x] 2.2 Tests in `tests/test_chronos_featurizer.py`: shape, determinism, sensitivity to selected_events, inhibited bit, is_experiential bit, delta time, source bucket overflow (8 cases)

## 3. CfC network

- [x] 3.1 Implement `kaine/modules/chronos/network.py` with `CfCNetwork` wrapping `ncps.torch.CfC`, exposing `tick(feature_vec) -> list[float]` (hidden state). Pins to CPU via `select_device("cpu")`; ignores attempts to force CUDA
- [x] 3.2 Expose `parameter_count()` so tests can assert <100K
- [x] 3.3 Tests in `tests/test_chronos_network.py`: parameter count cap, hidden state shape, state persistence across ticks, reset, input-size mismatch, force-cuda ignored (7 cases)

## 4. Anomaly and rumination

- [x] 4.1 Implement `kaine/modules/chronos/anomaly.py` with `AnomalyDetector` protocol + `RollingZScoreAnomaly` default
- [x] 4.2 Implement `kaine/modules/chronos/rumination.py` with `RuminationDetector` protocol, `RecurrenceRuminationDetector` default, and the habituation calculation
- [x] 4.3 Tests in `tests/test_chronos_anomaly.py` (7 cases) and `tests/test_chronos_rumination.py` (8 cases)

## 5. Module

- [x] 5.1 Implement `kaine/modules/chronos/module.py` with `Chronos(BaseModule)` — name="chronos", DI for featurizer / network / anomaly / rumination, configurable user-input streams list, baseline/alert salience
- [x] 5.2 `Chronos.initialize` resolves user-input stream cursors at the current latest entry id (so post-init events fire), starts the BaseModule workspace consumer (drives the producer logic via on_workspace) plus a separate task subscribing to user-input streams for time-since tracking
- [x] 5.3 `Chronos.shutdown` cancels the user-input subscriber and clears state
- [x] 5.4 Update `kaine/modules/__init__.py` to export `Chronos`

## 6. Config

- [x] 6.1 Add `[chronos]` block to `config/kaine.toml` with cfc units, anomaly window, rumination window/threshold/bucket resolution, baseline/alert salience, anomaly alert threshold, user_input_streams list
- [x] 6.2 Add `chronos = false` under `[modules]`

## 7. Module integration test

- [x] 7.1 `tests/test_chronos_module.py` against fakeredis: workspace broadcast → chronos.report with documented payload shape; rumination flag raises salience; user-input event resets time-since; ser/de roundtrips (7 cases)

## 8. Verification and cleanup

- [x] 8.1 Full unit suite passes (169 passed, 3 integration skipped 2026-05-19)
- [x] 8.2 `openspec validate chronos --strict` clean
- [x] 8.3 Update `DEPENDENCIES.md` ncps row to "in use by Chronos"
- [ ] 8.4 Commit, merge to main, archive change, drop branch
