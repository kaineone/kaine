## 1. Shared statistics
- [x] 1.1 `kaine/experiment/stats.py` (stdlib only): `mean`, population `std` and linear-interpolation `percentile`, each 0.0 on empty input.
- [x] 1.2 `kaine.experiment.stability`, `kaine.research.ignition_study.analysis` and `kaine.evaluation.observers.prediction_error_observer` import them instead of defining their own.
- [x] 1.3 Tests: the empty cases, the population std, and `percentile` against `numpy.percentile` on random inputs.

## 2. Embedder fallback
- [x] 2.1 `SidecarRegistry._embedder_fallback()` holds the fail-closed refusal and the logged `HashEmbedder` fallback; `_resolve_embedder` and `_embedder_default` call it.

## 3. Writers
- [x] 3.1 Record in the proposal why the plaintext JSONL writers are not routed through `AsyncJsonlSink`.
