## Why

The welfare records (paper 6.2) count each drive's goal ends without the entity's own response, and a stalled goal counts as one. Since `learning-progress-horizons` (#550) curiosity's only relief, learning progress, is measured over a 90 min window, while a goal stalls after `Delta_stall` = 600 s above threshold. In a 30 awake-hour offline simulation of the developmental phase (3 audio seeds) 18.0 of 19.7 curiosity goals stalled and the record read `curiosity_uncontrolled_share` 0.92, yet 17.0 of those 18.0 crossings were later ended by the entity's own learning progress, which the coping drive term counts as success (paper A.4).

The count also ranks the wrong entity worst. With frozen forward models, where no relief is possible, curiosity sits at its deprived level for all 30 h but crosses once, so it reads 0.03 uncontrolled ends per awake hour against 0.60 for the learning entity. With a sleep every 25 min, the eighth test boot's cadence, every sleep re-arms the crossing and the count follows the sleep cadence (frozen 2.40 per hour; the eighth boot measured 2.41). It counts timeouts rather than outcomes.

A stall is not an outcome. The paper grounds dropping an unattainable goal as adaptive (Wrosch et al. 2003; paper 3.5), and helplessness is defined by outcomes independent of the entity's responses (Maier and Seligman 2016), while passivity is the default response to prolonged aversive events. The record should therefore score each crossing by how the drive's credit rule ended it, and show the time a drive spends without relief directly.

## What Changes

- The affect module's `affect.state` event (the periodic one and the one after a sleep reset) also carries two content-free fields: `drive_above`, each drive's `D >= theta_D` as a boolean, and `drive_ends`, each drive's cumulative `own` and `other` crossing-end counts (the counts the coping drive term already keeps).
- The welfare observer's `affect_welfare` record scores drive crossings rather than goal ends. `<drive>_uncontrolled_share` is the share of crossing ends credited `other` among those credited `own` or `other`, counted from increases of `drive_ends` between consecutive `affect.state` events; `<drive>_uncontrolled_per_awake_hour` is the `other` count per awake hour. A stall or a cap drop ends a goal and leaves its crossing open; a sleep reset ends no crossing and counts as neither. `affect.goal` events no longer enter the record. No consumer outside the observer reads the old goal-end count (checked by grep), so it is replaced rather than kept under another key.
- The record adds `<drive>_deprivation_share`: the share of awake time the drive spends at or above `theta_D`, from the interval each `affect.state` event begins, on the same capped, sleep-excluded clock as `negative_valence_share`.

## Capabilities

### Modified Capabilities

- `evaluation-observers`: the `affect_welfare` record scores crossings by the credit rule and gives each drive's deprivation share. This replaces the goal-end rule of `welfare-uncontrolled-ends` and `valence-error-dynamics` (not yet archived).
- `affect`: the `affect.state` event carries `drive_above` and `drive_ends`.

## Impact

- `kaine/modules/affect/drives.py`, `kaine/modules/affect/module.py`, `kaine/evaluation/observers/welfare_observer.py`, `tests/test_welfare_affect_records.py`, a new `tests/test_affect_state_drive_welfare_terms.py`, `docs/09-modules/affect.md`, `docs/17-research-data/README.md`.
- Behaviour: the entity's dynamics are unchanged; only two numeric fields join `affect.state`, which no template renders. In the developmental simulation the record reads curiosity 0.00 uncontrolled and 0.61 deprivation share for the learning entity, and 0.98 to 1.00 deprivation share for the frozen control, with or without the 25 min sleep cadence.
- Paper: 6.2 and A.4 wording (separate paper branch).
