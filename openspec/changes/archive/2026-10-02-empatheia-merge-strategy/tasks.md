## 1. Strategy
- [x] 1.1 Move `EmpatheiaMergeStrategy` and `_merge_profiles` from `kaine/modules/empatheia/store.py` to `kaine/lifecycle/strategies.py` unchanged in behaviour; register `"empatheia"` in `default_strategies()`.
- [x] 1.2 Remove `apply_merged_state`; drop both names from `kaine/modules/empatheia/__init__.py`; update the store's module docstring.

## 2. Tests
- [x] 2.1 `tests/test_empatheia_merge.py` imports the strategy from its new home; the `apply_merged_state` tests go.
- [x] 2.2 New: `ForkManager.merge` over two real snapshots with Empatheia state (counts 5 and 3, A larger) yields 8, the count-weighted histogram, min `first_seen` and max `last_seen`.
- [x] 2.3 New: `default_strategies()["empatheia"]` is the Empatheia strategy.

## 3. Docs
- [x] 3.1 `docs/09-modules/empatheia.md` and `docs/12-forks-and-merges.md` describe the reconciled merge.
