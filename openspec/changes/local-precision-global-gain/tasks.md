## 1. Selection

- [x] 1.1 `RuleBasedSalience` drops the precision argument and weight; priority is `clip(intensity * novelty * goal)`.
- [x] 1.2 Delete `kaine/workspace/precision.py`, `make_source_precision`, its exports and call site, and the four `[syneidesis]` keys (allow-list and shipped config).
- [x] 1.3 Drop the per-source weight requirement from the active `precision-weighted-selection` change.

## 2. Profile

- [x] 2.1 `thesis_test.toml`: `[lingua].temperature = 0.0`; comments say arousal is the global gain.

## 3. Tests and docs

- [x] 3.1 Remove the `SourcePrecision` and `make_source_precision` tests; keep the contrast tests.
- [x] 3.2 Test: a constant-intensity heartbeat source does not lower a perceptual alert's score.
- [x] 3.3 Test: the thesis profile resolves `[lingua].temperature` to 0.0.
- [x] 3.4 Docs updated.
