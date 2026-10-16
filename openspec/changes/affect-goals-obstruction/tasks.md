## 1. Goal ledger

- [ ] 1.1 Give `Goal` an optional `drive` and `likelihood`, persist them, look up a drive's active goal, set a goal's likelihood, and remove the active goals without counting them
- [ ] 1.2 Keep running completed and abandoned counts and retain at most 256 finished goals; tests

## 2. Affect module

- [ ] 2.1 Create a goal on each drive crossing unless the drive has one, with priority the crossing value and `L` the drive's success ratio; enforce the cap by abandoning the lowest priority
- [ ] 2.2 Complete or abandon a drive goal when its drive's own or other end count rises, and abandon it after `goal_stall_s` at or above threshold
- [ ] 2.3 Open a response window on each non-rest intent, lower `L` by `goal_likelihood_fall × L` when the drive does not fall within `goal_response_window_s`, and hold `ΔL` for the next appraisal
- [ ] 2.4 Score the goal as `clip(r - o, -1, 1)` with `o = v* × ΔL` for the dominant drive's goal, check coping when the score is nonzero, publish `obstruction`
- [ ] 2.5 Clear active goals, windows and held obstruction on the sleep reset; publish `affect.goal` for each lifecycle change
- [ ] 2.6 `[affect]` config keys `goal_stall_s`, `goal_cap`, `goal_response_window_s`, `goal_likelihood_fall` in the factory and `config/kaine.toml`

## 3. Tests and docs

- [ ] 3.1 Tests for every rule: creation, no duplicate, completion, abandonment by other end, stall and cap, likelihood fall and its absence, obstruction for the dominant goal only, a negative score reaching anger, coping on a negative score, the sleep reset, persistence, and unchanged appraisal with no active goal
- [ ] 3.2 Docs: the goal lifecycle, obstruction, the bipolar score, anger as at best irritation, the new keys
