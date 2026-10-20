## Why

The paper's A.4 (predictive-workspace-paper #47) now specifies where the affect module's goals come from and how a failed response obstructs them, in its *Goals.* and *Obstruction.* paragraphs. Goals come from drive crossings and end as completed or abandoned; each carries an expected-relief likelihood that falls when the entity's responses bring no relief; conduciveness is bipolar, so the goal score is `clip(r - o, -1, 1)`. The code has a goal ledger that nothing fills outside tests, a goal score that cannot go negative, and a sleep reset that keeps the active goals although A.4's *Sleep.* item clears them. Anger, which needs a negative goal score, can never fire. §5.4 lists goal generation and obstruction as specified and not yet built.

## What Changes

- **Goals from crossings.** A crossing of a drive's threshold creates the goal of relieving that drive (description `relieve <drive>`, priority = the drive value at the crossing) unless that drive already has an active goal. Intents are responses, never goal sources.
- **Completion and abandonment.** A drive goal completes when its drive falls below the re-arm band and the existing credit rule counts the fall as the entity's own (`own_ends` increments). It is abandoned when the fall counts as other (`other_ends` increments), when the drive stays at or above its threshold for `goal_stall_s` (Δ_stall, 600 entity s) without a break, or, as the lowest priority (ties to the earliest created), when active goals exceed `goal_cap` (n_goal, 3). These outcomes feed the ledger's completed and abandoned counts that coping already uses. Each lifecycle change publishes `affect.goal` as the existing add, complete and abandon methods do, with the drive and a reason.
- **Expected-relief likelihood.** Each drive goal carries `L` in `[0, 1]`, set at creation to its drive's success ratio `p = (s + 1) / (s + f + 2)`. An intent other than `intent.rest`, made while the goal is active, opens a response window of `goal_response_window_s` (Δ_resp, 10 entity s) against the drive's value just before the intent. If no update within the window sees the drive below that value, `L` falls by `ΔL = goal_likelihood_fall × L` (η_L, 0.5), and `ΔL` is held for the next appraisal.
- **Bipolar goal score.** The next appraisal takes the obstruction `o = v* × ΔL` from the dominant drive's goal (its held `ΔL` summed if several windows closed), and `o = 0` otherwise; every held `ΔL` is cleared after that appraisal. The goal score is `clip(r - o, -1, 1)`, with `r` the conducive part as before. With no injected drive table there is no dominant drive and `o = 0`.
- **Coping when the goal score is nonzero.** Coping is checked when the goal score is nonzero (negative included), and is unavailable only at exactly 0. The term that sets `r` supplies `p`, the drive term on a tie, as before.
- **Sleep reset clears the active goals.** They are removed without counting as completed or abandoned, as a sleep reset counts as neither for the drives; pending response windows and held obstruction clear too.
- **Persistence.** Goals, their drive and their likelihood survive serialize and deserialize. The ledger keeps running completed and abandoned counts and retains at most the 256 most recent finished goals, so a long run does not grow the preserved state without bound; the counts still include the pruned goals. Response windows and stall timers are transient and restart after a restore.
- **Anger becomes reachable.** With a negative goal score below -0.3 and coping at least 0.3, `classify()` returns anger. Anger here matches at best Sander, Grandjean and Scherer's (2005, Table 3) irritation profile: KAINE attributes no obstruction to another agent and has no standards check, so the rage profile is out of reach.
- **Config.** `[affect]` gains `goal_stall_s = 600.0`, `goal_cap = 3`, `goal_response_window_s = 10.0` and `goal_likelihood_fall = 0.5`, the Table A1 defaults.
- `affect.emotion` carries the `obstruction` it applied.

## Capabilities

### Modified Capabilities

- `affect`: goals come from drive crossings and end by the credit rule, a stall or the cap; failed responses lower a goal's likelihood and obstruct the dominant drive's goal, so the goal score is bipolar.

## Impact

- `kaine/modules/affect/goals.py`, `kaine/modules/affect/module.py`, `kaine/boot/factories/affect.py`, `config/kaine.toml`, `docs/09-modules/affect.md`, `docs/appendix-a-configuration/modules.md`, new `tests/test_affect_goal_lifecycle.py`, additions to `tests/test_affect_goals.py`.
- Behaviour: drive crossings now publish `affect.goal` events and populate the ledger, so while a drive goal is active the token-overlap term is computed alongside the drive term. With no goal active the appraisal is unchanged. A sleep reset removes active goals.
