## Why

The welfare record counted a deficit's crossings only when they ended, by the entity's own response or otherwise. Two cases left no trace. The sleep reset clears a drive's crossing latch without counting an end, and a goal that stalls or loses to the goal cap leaves its crossing open. A deficit held above threshold past the stall horizon, the case closest to the helplessness the record tracks (Maier and Seligman 2016), therefore never entered the uncontrolled share. In the tenth test boot boredom had 95 crossings, 85 ended by the entity's own response, 8 otherwise and 2 by the sleep reset; the record showed 93. The paper (predictive-workspace-paper #48, section 6.2) now has the record give each deficit's ends by sleep reset and its crossings still open.

## What Changes

- A deficit drive counts the crossings the sleep reset ends (`Drive.sleep_reset()`, used by `DriveSet.reset_deficits()`); the count persists in the affect snapshot under `drive_reset_ends`.
- `affect.state` adds `drive_reset_ends` (each deficit's cumulative count) and `drive_open` (whether each deficit's crossing latch is set). `drive_ends` keeps its `{own, other}` shape. The research log keeps both new fields.
- The `affect_welfare` record adds, per deficit, `<drive>_sleep_reset_ends` (counted from `drive_reset_ends` like the other ends: first value a baseline, a fall re-baselines) and `<drive>_open_crossings` (1 or 0 from the latest `drive_open`, null before any).
- The uncontrolled share, the per-hour count and the deprivation share are unchanged.

## Capabilities

### Modified Capabilities

- `welfare-monitoring`: the affect welfare record gives ends by sleep reset and open crossings.
- `affect`: the state event carries the sleep-reset end counts and the open flags.

## Impact

- `kaine/modules/affect/drives.py`, `kaine/modules/affect/module.py`, `kaine/evaluation/observers/welfare_observer.py`, `kaine/evaluation/observers/research_event_observer.py`, `docs/09-modules/affect.md`, `docs/17-research-data/README.md`, tests.
- Behaviour: none for the entity. Two keys more in `affect.state`, one (`drive_reset_ends`) in the snapshot (the open flags come from the persisted crossing latches), and two keys more per deficit in the welfare record.
