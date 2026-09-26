## 1. Implementation

- [x] 1.1 `GoalLedger.to_dict` / `from_dict`; Thymos saves and restores its goals.
- [x] 1.2 `RestScheduler.export_remaining` / `restore_remaining`; Hypnos saves and restores its schedule as time remaining.
- [x] 1.3 `PymdpEngine.seed_posterior`; Nous restores the posterior into its engine.

## 2. Verification

- [x] 2.1 Unit tests: the goal ledger round-trips, including completed and abandoned goals, and drops invalid entries; the schedule round-trips on a fake clock across a long simulated gap, an overdue schedule stays overdue, a snapshot without a schedule starts fresh, non-finite values are refused; the Nous engine's degraded step after a restore returns the preserved posterior, and a mismatched posterior is ignored.
- [x] 2.2 Every module's snapshot survives a JSON round-trip into a fresh instance (all sixteen; configuration echoed into a snapshot follows the current configuration), and a study-order chain preserves and revives with one more module per step, checking every captured module and the fresh new one (`tests/test_revive_each_module.py`).
- [x] 2.3 Offline suite green; `openspec validate snapshot-completeness --strict`.
