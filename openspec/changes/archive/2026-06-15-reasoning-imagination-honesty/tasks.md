## 1. H1 — Nous inference-crash honesty

### 1.1 `kaine/modules/nous/engine.py`
- [x] 1.1.1 Add `error: bool = False` and `error_reason: str = ""` fields to `EngineResult`
- [x] 1.1.2 Update `EngineResult` docstring to document mutual-exclusion with `timed_out`
- [x] 1.1.3 `PymdpEngine.step()` `except Exception` block: log at `ERROR` level, set `error=True`, set `error_reason`
- [x] 1.1.4 `FakeEngine`: add `error_on: Optional[int]` parameter; return `error=True` result on the scripted step

### 1.2 `kaine/modules/nous/module.py`
- [x] 1.2.1 `on_workspace`: on `result.error`, call `_publish_error()` and return (skip belief/policy)
- [x] 1.2.2 Add `_publish_error()` method that publishes `nous.error` with `error_reason`, `elapsed_ms`, `num_factors`, `num_actions`
- [x] 1.2.3 Update module docstring to document `nous.error`

## 2. H7 — Phantasia backend disclosure

### 2.1 `kaine/modules/phantasia/module.py`
- [x] 2.1.1 `_publish_world_error()`: add `"backend": self._backend` to payload
- [x] 2.1.2 `generate_scenario()`: add `"backend": self._backend` to payload

### 2.2 `config/kaine.toml`
- [x] 2.2.1 `[phantasia]` comment: plainly state that `backend = "fake"` is a non-learning EMA stub

## 3. M5 — Salience factor bypass warning

### 3.1 `kaine/workspace/salience.py`
- [x] 3.1.1 Import `StaticGoalScorer`, `StaticThymosModulator` from strategies
- [x] 3.1.2 `RuleBasedSalience.__init__()`: `isinstance` check; `log.warning` naming bypassed factors

## 4. L1 — Reserved feature slot documentation

### 4.1 `kaine/modules/chronos/featurizer.py`
- [x] 4.1.1 Add explicit comment at vec[23] documenting the permanent-zero invariant and retrain cost

## 5. Tests

### 5.1 `tests/test_nous_engine.py`
- [x] 5.1.1 `test_engine_result_error_defaults_false`
- [x] 5.1.2 `test_engine_result_error_fields_populate`
- [x] 5.1.3 `test_fake_engine_error_on_returns_error_result`
- [x] 5.1.4 `test_timeout_and_error_mutually_exclusive_in_fake`

### 5.2 `tests/test_nous_module.py`
- [x] 5.2.1 `test_inference_crash_publishes_nous_error`
- [x] 5.2.2 `test_inference_crash_suppresses_belief_and_policy`
- [x] 5.2.3 `test_inference_crash_after_good_cycle_does_not_republish_stale`
- [x] 5.2.4 `test_timeout_still_publishes_belief_not_error`

### 5.3 `tests/test_phantasia_module.py`
- [x] 5.3.1 `test_world_error_discloses_backend`
- [x] 5.3.2 `test_scenario_discloses_backend`
- [x] 5.3.3 `test_backend_value_matches_constructor_arg`
- [x] 5.3.4 Update `test_world_error_carries_no_scenario_content` to allow `backend` key

### 5.4 `tests/test_workspace_salience.py`
- [x] 5.4.1 `test_static_goal_scorer_warns_at_construction`
- [x] 5.4.2 `test_static_thymos_modulator_warns_at_construction`
- [x] 5.4.3 `test_warning_names_bypassed_factors`
- [x] 5.4.4 `test_no_warning_for_real_scorers`
- [x] 5.4.5 `test_warning_includes_constant_value`

### 5.5 `tests/test_chronos_featurizer.py`
- [x] 5.5.1 `test_reserved_slot_23_is_always_zero`
- [x] 5.5.2 `test_feature_dim_unchanged`

## 6. Targeted test run
- [x] 6.1 `.venv/bin/python -m pytest -q -p no:cacheprovider tests/ -k "nous or phantasia or salience or syneidesis or strategies or chronos"` — all green
