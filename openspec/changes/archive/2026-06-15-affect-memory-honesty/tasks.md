## 1. H2 — Thymos norm_compatibility disclosure
- [x] 1.1 Add `norm_compatibility_available: False` to `thymos.emotion` publish payload
- [x] 1.2 Update `_score_snapshot` comment to state DISGUST is unreachable by design

## 2. M4 — Thymos goal_significance disclosure + no-goals guard
- [x] 2.1 Add `goal_significance_method: "token_overlap_v1"` to `thymos.emotion` publish payload
- [x] 2.2 `GoalLedger.relevance()`: return `0.0` when no active goals (no spurious positive)
- [x] 2.3 Update `relevance()` docstring to disclose the token_overlap_v1 method

## 3. M3 — PassiveDecay first-use log
- [x] 3.1 Add `import logging` + `log` to `regulation.py`
- [x] 3.2 `PassiveDecay.__init__` records `_logged_once = False`
- [x] 3.3 `PassiveDecay.suggest()` emits one-time `log.debug` on first call

## 4. H3 — Audition degraded flag
- [x] 4.1 `_publish_emotion` checks `result.raw.get("degraded")` and adds `degraded: True` to payload

## 5. L2 — Empatheia degraded gate
- [x] 5.1 `_handle_emotion` returns early when `payload.get("degraded")` is truthy

## 6. M7 — Mnemos StorageError
- [x] 6.1 Add `StorageError` class to `mnemos/storage.py`
- [x] 6.2 `QdrantStorage.search()` raises `StorageError` instead of returning `[]`
- [x] 6.3 `mnemos/memory.py` imports `StorageError` (propagates naturally from recall)
- [x] 6.4 `Mnemos.recall()` catches `StorageError`, logs error, publishes `mnemos.recall` with `error: True`
- [x] 6.5 Export `StorageError` from `mnemos/__init__.py`

## 7. Tests
- [x] 7.1 `tests/test_affect_memory_honesty.py`: H2 norm_unavailable flag in thymos.emotion
- [x] 7.2 tests: M4 goal_significance_method in thymos.emotion
- [x] 7.3 tests: M4 no-goals guard returns 0.0
- [x] 7.4 tests: M3 PassiveDecay logs once on first use
- [x] 7.5 tests: H3 degraded flag in audition.emotion
- [x] 7.6 tests: L2 empatheia skips degraded fold
- [x] 7.7 tests: M7 StorageError raised by QdrantStorage.search
- [x] 7.8 tests: M7 mnemos.recall carries error=True on StorageError
- [x] 7.9 Targeted suite green
