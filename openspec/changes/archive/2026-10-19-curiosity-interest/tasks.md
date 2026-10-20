## 1. Implementation

- [x] 1.1 `Drive` gains a heterostatic mode (no relief, re-arm without counting an end); `DriveSet` curiosity defaults (decay 0.00096 with its derivation, no relief), the progress build input, boredom's learning-progress build and no-response counterfactual, and deficit-only reset; `GoalLedger.clear_active_for_drive`
- [x] 1.2 Affect module: boredom relief `max(lp+, exc)` with the own credit split, curiosity build `lp+`, arousal target and goal creation over deficits, a sleep reset that keeps interest and its latch, `curiosity_scheme` in state and the migration of older checkpoints
- [x] 1.3 Welfare record: `curiosity_interest_share` in place of curiosity's cost keys
- [x] 1.4 Run manifest `curiosity_scheme`; felt phrase, drive-policy and config wording
- [x] 1.5 Tests: new semantics, migration, persistence through sleep and restart; existing tests that used curiosity as a generic goal drive move to a deficit
- [x] 1.6 Docs: affect module page and research-data record description
- [x] 1.7 Harness: arms A, C and D-new on the shipped affect module, learning and frozen, with and without a 25 min sleep cadence
