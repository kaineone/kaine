## 1. Implementation

- [x] 1.1 Publish an `affect.goal` event with action `cleared` and reason `sleep_reset` for every goal the affective reset clears, leaving the ledger's completed and abandoned counts unchanged
- [x] 1.2 Save each drive's crossing latch with the module state and restore it, inferring it from value and threshold for state that lacks it
- [x] 1.3 Make `classify()` return fear only for Table 3's fear profile (low pleasantness, high novelty, an obstructed goal, very low coping), and update the tests that assumed the old rule
- [ ] 1.4 Update `docs/09-modules/affect.md` (goal events, reset, persistence, categories) and run the affect, appraisal, goal, drive, sleep and revive tests and the full suite
