## Why

SHALL: Six "pretend process" findings identified in the 2026-06-09 audit expose
cases where internal modules publish events or return values that silently
fabricate success, hide unavailability, or present undisclosed proxies as
measured quantities.  Each is a honesty/integrity violation under the
no-pretend-processes principle.

- **H2**: `thymos.emotion` publishes `norm_compatibility` as if it were a real
  Scherer appraisal reading, but it is hardcoded `0.0` (Eidolon integration
  not wired).  DISGUST is therefore silently unreachable.
- **H3**: `audition.emotion` publishes a `category="neutral", confidence=0.0`
  result when funasr is absent — indistinguishable from a real low-confidence
  reading to consumers.
- **L2**: Empatheia folds every `audition.emotion` event (including degraded
  ones from H3) into the agent model, inflating interaction counts and
  familiarity from non-running inference.
- **M3**: `PassiveDecay.suggest()` returns a zero `RegulationAdjustment` on
  every tick with no trace — a completely invisible no-op.
- **M4**: `GoalLedger.relevance()` is a bag-of-words token-overlap heuristic
  published as `goal_significance` in `thymos.emotion` with no disclosure.
  Also: when no goals are registered, the function returns a small spurious
  positive rather than `0.0`.
- **M7**: `QdrantStorage.search()` catches all exceptions and returns `[]`,
  so a Qdrant failure looks identical to "no relevant memories".  Mnemos then
  publishes `mnemos.recall` with `count=0` as if the search succeeded.

## What Changes

- `thymos.emotion` events carry `norm_compatibility_available: false` and
  `goal_significance_method: "token_overlap_v1"` to disclose dimension
  unavailability and proxy method.
- `audition.emotion` events carry `degraded: true` when the emotion model
  did not run.
- Empatheia gates the agent-model fold on the absence of `degraded: true`.
- `PassiveDecay` emits a one-time debug log on first use.
- `GoalLedger.relevance()` returns `0.0` when no active goals exist.
- `QdrantStorage.search()` raises `StorageError` on failure; `Mnemos.recall()`
  catches it, logs `error`, and publishes `mnemos.recall` with `error: true`.

## Capabilities

### New Capabilities

<!-- none -->

### Modified Capabilities

- `thymos`: `thymos.emotion` event payload carries honesty metadata
  (`norm_compatibility_available`, `goal_significance_method`); `GoalLedger`
  no-goals guard; `PassiveDecay` first-use log.
- `audition`: `audition.emotion` event payload carries `degraded: true` when
  the emotion model did not classify.
- `empatheia`: `_handle_emotion` skips the fold when `degraded: true`.
- `mnemos`: `QdrantStorage.search()` raises `StorageError`; `Mnemos.recall()`
  catches and publishes with `error: true` instead of a fake empty result.

## Impact

- **Code (edit):**
  `kaine/modules/thymos/module.py` (H2 + M4 flags in thymos.emotion publish),
  `kaine/modules/thymos/goals.py` (M4 no-goals guard + docstring),
  `kaine/modules/thymos/regulation.py` (M3 first-use log),
  `kaine/modules/audition/module.py` (H3 degraded flag in _publish_emotion),
  `kaine/modules/empatheia/module.py` (L2 degraded gate in _handle_emotion),
  `kaine/modules/mnemos/storage.py` (M7 StorageError class + QdrantStorage.search raise),
  `kaine/modules/mnemos/memory.py` (M7 StorageError import),
  `kaine/modules/mnemos/module.py` (M7 catch + publish error: true),
  `kaine/modules/mnemos/__init__.py` (M7 StorageError export).
- **Tests:** `tests/test_affect_memory_honesty.py` (all six findings covered).
- **Safety:** All changes fail closed or disclose; no behaviour is removed,
  only made visible.  No module-enable flag is touched.
