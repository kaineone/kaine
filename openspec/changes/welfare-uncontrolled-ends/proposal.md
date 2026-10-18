## Why

The paper's welfare records (paper 6.2) give "each drive's share of goal ends without the entity's own response", and A.4 lists three ways a goal is abandoned: the fall came without the entity's response, the drive stayed above `theta_D` for `Delta_stall`, or (lowest priority) active goals exceeded `n_goal`. A sleep reset counts as neither. The welfare observer's `AffectWelfareTally` counted only `abandoned`/`without_response` as uncontrolled, so goals that stalled or lost to the cap were dropped from both the numerator and the denominator. In a test boot curiosity read `curiosity_uncontrolled_share` null despite three stalls and one own completion.

The same boot showed a second defect: two goals stalled 10.2 minutes after a restore at goal lives of about 1176 s and 620 s, because the stall clock (`_goal_above_since`) is not persisted. `Delta_stall` is on the entity clock (Table A1), and module state persists with the entity so that a restart neither resets nor repeats it (paper A.7), so a restored goal must keep the above-threshold time it had already accumulated.

## What Changes

- `AffectWelfareTally.observe_goal` counts every abandoned end with reason `without_response`, `stalled` or `cap` as uncontrolled ("other"); `completed` with `own_response` stays "own"; `cleared`/`sleep_reset` counts as neither. Any other action or reason counts as neither, so an unknown reason is never credited silently.
- The affect module's `serialize()` stores, per active goal with a running stall clock, the elapsed above-threshold seconds as `goal_above_elapsed`; `deserialize()` sets each restored active goal's since-time to the restore time minus that elapsed time, so the stall horizon carries over. State without the field, or with an invalid entry, restores as before (the clock restarts at the first update).
- The coping ledger term already counts stalled and cap-dropped goals as abandoned (`GoalLedger` counts every transition to `ABANDONED`), so no ledger change is needed.

## Capabilities

### Modified Capabilities

- `evaluation-observers`: the `affect_welfare` record counts stalled and cap-dropped goals as ends without the entity's own response. This corrects the uncontrolled-end rule added by `valence-error-dynamics` (not yet archived), whose requirement text and scenario are amended to match.
- `affect`: the goal stall clock persists across a restore.

## Impact

- `kaine/evaluation/observers/welfare_observer.py`, `kaine/modules/affect/module.py`, `tests/test_welfare_affect_records.py`, a new `tests/test_affect_stall_clock_persistence.py`, `docs/09-modules/affect.md`, `docs/17-research-data/README.md`, and the `valence-error-dynamics` change's `evaluation-observers` spec delta.
- Behaviour: `<drive>_uncontrolled_share` and `<drive>_uncontrolled_per_awake_hour` rise for drives whose goals stall or lose to the cap. A goal restored after a restart stalls `Delta_stall` after it first stayed above threshold, not `Delta_stall` after the restore.
