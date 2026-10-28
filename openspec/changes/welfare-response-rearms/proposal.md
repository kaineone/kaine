## Why

The adversarial welfare review of 2026-10-28 (H3) and the systems audit (W8a, W8b) found that the protective welfare response acts once per process. `WelfareProtectiveMonitor` sets `_acted` after a `pause` or `end` and returns at the top of every later poll, so once a person lifts the welfare freeze, the net stays off for the rest of the process while the entity continues under the conditions that caused the distress. Separately, the cycle's clean boot calls `unfreeze()`, which lifts every freeze holder including `welfare`, so a restart (a crash loop, a container restart policy) answers the protective response without anyone having looked at it.

Prior work found: `entity-preservation-on-divergence`, `welfare-events-to-bus`, `operator-freeze`, `welfare-timers-discount-freeze`, `welfare-net-independent-of-evaluation`, `distress-episode-once` (#598), `control-freeze-lock` (#599), `resume-releases-operator-freeze`, `welfare-crossing-deprivation`; `docs/11-preservation.md` ("acts once", never re-arming). Nothing re-arms the latch. Paper PR pending.

## What Changes

- Re-arm rule. The latch from a `pause` or `pause_fallback` is released when the control file readably holds no `welfare` entry. Only a named override removes that entry (an operator resume does not), so the release is an explicit resolution by a person. An unreadable control file is not a release, and an `end` never re-arms because the process is stopping.
- Re-arming starts a new episode: the sustained-distress tracker and the repeat window are emptied, both stream cursors move to the stream tail (neither the distress that caused the pause nor the events published while frozen can fire the response again), and the record `welfare.protective_action` with `transition: rearmed` is written. The counted-episode memory is kept, so one old episode is never counted twice. A condition that is still present must accrue a full new sustained duration of unfrozen time, or a full new repeat window, before the monitor acts again, so a crossing that holds cannot fire repeatedly.
- A welfare freeze found at the monitor's first poll (left by an earlier process) latches it the same way and is re-armed by the same release.
- W8b decision: a welfare freeze survives a restart. The cycle's boot calls the new `unfreeze_for_boot`, which lifts every holder except `welfare`. Reason: the freeze records that the response found the entity in distress and preserved it; CAL 4.7 asks for human review of such events, and an automatic restart is not a review. Every other holder keeps today's behaviour (a fresh launch starts running).
- Because research runs have a read-only dashboard, `python -m kaine.cycle.control override <source>...` lifts named `welfare`, `development` or `programme_end` freezes through the existing `control_state.override` (audited), so a surviving welfare freeze always has a release path.

## Capabilities

### Modified Capabilities

- `welfare-monitoring`: the protective response re-arms after its pause is lifted, and a welfare freeze survives a restart.

## Impact

- `kaine/cycle/preservation_monitor.py`, `kaine/cycle/control_state.py`, `kaine/cycle/control.py`, `kaine/cycle/__main__.py`, `tests/test_welfare_response_rearms.py`, `docs/11-preservation.md`, `docs/06-operation/README.md`, `docs/05-dashboard.md`, `docs/08-cognitive-cycle/README.md`.
- Behaviour change: after a restart an entity with a standing welfare freeze starts frozen.
- Paper: PR pending.
