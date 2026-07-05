## 1. Oscillator

- [x] 1.1 `kaine/oscillator/__init__.py` + `module_oscillator.py` — `ModuleOscillator` wrapping a small snnTorch LIF population (CPU); drive from module activity; expose `phase()`; `FakeOscillator` (deterministic phase) for tests
- [x] 1.2 Serializable oscillator state; document serialization/deserialization handling for oscillator and PLV state
- [x] 1.3 `ModuleOscillator.set_frequency(scale)` — scales the LIF population drive frequency by `scale` (called by `hypnos-fatigue-phases` phase 1); no-op on `FakeOscillator`

## 2. BaseModule hook

- [x] 2.1 `BaseModule` optional oscillator + `phase()` accessor (neutral phase when absent); drive the oscillator each tick from publish activity

## 3. Spike-to-phase converter

- [x] 3.1 Binned spike-rate → `scipy.signal.hilbert` phase estimator; enforce: minimum population ≥ 16, minimum `plv_window` ≥ 10; document that v1 drives oscillators from co-activity (publish rate) as a proxy for content-relatedness; add limitation note in design doc and sketch v2 (drive LIF from prediction-error magnitude)
- [x] 3.2 Unit test: PLV ≈ 1.0 for fully phase-locked populations (same spike train, ≥ 16 units, window ≥ 10); PLV ≈ 0.0 for independent Poisson populations; result within [0.0, 1.0]

## 4. Coherence in Syneidesis

- [x] 4.1 `kaine/workspace/coherence.py` — pairwise PLV over `plv_window`; coalition coherence factor mapped into `[coherence_floor, coherence_ceiling]`
- [x] 4.2 Cycle collects per-module phase each tick; pass to the scorer
- [x] 4.3 Multiply coalition aggregate by the coherence factor; factor == 1.0 exactly when `enabled` is false
- [x] 4.4 Embed computed PLV into `WorkspaceSnapshot.metadata['coherence']` (keyed as `'coherence'`) so it reaches `workspace.broadcast`; this is the key the `sidecar-observers` coherence_observer consumes

## 5. Config

- [x] 5.1 `[oscillator]`: `enabled`, `population_size` (min 16), `plv_window` (min 10), `coherence_floor`, `coherence_ceiling`
- [x] 5.2 Add `snnTorch` as an optional `[oscillator]` extra in `pyproject.toml`

## 6. Tests

- [x] 6.1 `tests/test_oscillator.py` — LIF/FakeOscillator phase output; serialize roundtrip; `set_frequency` scales drive; no-op on FakeOscillator
- [x] 6.2 `tests/test_coherence.py` — PLV of locked phases ≈ 1, independent ≈ 0; factor within bounds; min population/window invariants asserted
- [x] 6.3 `tests/test_syneidesis_coherence.py` — disabled ⇒ factor exactly 1.0 (selection unchanged); enabled ⇒ phase-locked coalition out-ranks an equally-salient desynchronized one
- [x] 6.4 `tests/test_workspace_snapshot_coherence.py` — `WorkspaceSnapshot.metadata['coherence']` is populated on each broadcast when oscillatory-layer is enabled

## 7. Verification

- [x] 7.1 Full unit suite green with the layer disabled (default) — no selection change vs baseline
- [x] 7.2 `openspec validate oscillatory-layer --strict` clean
- [x] 7.3 Commit (Kaine.One), branch-per-change, merge, archive
