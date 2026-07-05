## 1. Strategy and helpers

- [x] 1.1 Implement `kaine/workspace/strategies.py` with `SalienceStrategy`, `GoalScorer`, `ThymosModulator` protocols plus `StaticGoalScorer` and `StaticThymosModulator` defaults
- [x] 1.2 Implement `kaine/workspace/novelty.py` with `NoveltyTracker` (deque-backed) and `fingerprint(event)` helper

## 2. Salience

- [x] 2.1 Implement `kaine/workspace/salience.py` with `RuleBasedSalience` v1 implementing `intensity * novelty * goal_relevance * thymos_modulation` clamped to `[0, 1]`

## 3. Syneidesis

- [x] 3.1 Implement `kaine/workspace/syneidesis.py` with `Syneidesis.select`, `set_top_k`, `set_publication_threshold`
- [x] 3.2 Implement empty-event-list inhibited-snapshot path
- [x] 3.3 Implement strategy error tolerance

## 4. Tests

- [x] 4.1 Write `tests/test_workspace_novelty.py` covering first-observation novelty, monotonic decrease, window eviction
- [x] 4.2 Write `tests/test_workspace_salience.py` covering product form, term zeroes, clamping, error tolerance
- [x] 4.3 Write `tests/test_workspace_syneidesis.py` covering top-k, inhibition flag, empty events, fewer-than-k, runtime mutators
- [x] 4.4 Write `tests/test_workspace_strategy_substitution.py` proving a custom `SalienceStrategy` plugs in without code changes — folded into `test_workspace_syneidesis.py::test_custom_strategy_substitutes_cleanly`

## 5. Integration

- [x] 5.1 Update `kaine/workspace/__init__.py` exports
- [x] 5.2 Add `kaine.workspace` to `pyproject.toml` packages list
- [x] 5.3 Run unit tests; all pass (66 passed, 3 integration skipped 2026-05-18)
- [ ] 5.4 Commit
- [ ] 5.5 `openspec validate syneidesis --strict` clean
