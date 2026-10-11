## 1. Timespans

- [x] 1.1 `numpy_cfc_step(..., ts=1.0)`; NumPy and torch parity with timespans.
- [x] 1.2 `SubstrateForwardModel.step/predict(feature, timespan=1.0)` and `CfCNetwork.tick(feature_vec, timespan=1.0)`, both declaring `accepts_timespan = True`.
- [x] 1.3 Soma passes `dt / read_interval_s`, Chronos `dt / running mean of dt` (32 broadcasts), clipped to `[0, 10]`, 1.0 on the first step; only to models that declare `accepts_timespan`.

## 2. VRAM feature

- [x] 2.1 `metrics_to_feature_vector` slot 7 = hottest `gpu_*_vram_percent / 100`, when layout 2.
- [x] 2.2 Soma `feature_layout` 2 in snapshots; untagged snapshots restore with layout 1 (slot 7 at 0.0).

## 3. Tests, docs

- [x] 3.1 Tests: `ts = 1` reproduces the previous step bit-for-bit; other `ts` changes the state; torch parity with timespans when torch is present; Soma and Chronos pass the normalised timespan; a plugin model without `accepts_timespan` is called without it; VRAM in slot 7; layout restore; mutation-check.
- [x] 3.2 Docs: `docs/09-modules/soma.md`, `docs/09-modules/chronos.md`.
- [x] 3.3 `openspec validate reservoir-timespan-soma-vram --strict`.
