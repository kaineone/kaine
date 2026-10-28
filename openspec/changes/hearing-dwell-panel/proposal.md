## Why

The development panel shows the hearing stage and band, for example "stage 3 of 4, below 1732.1 Hz", but not the stage's dwell: the awake time spent in the stage against `min_dwell_seconds` (5400) and `max_dwell_seconds` (25200). The 12th test boot found the dwell missing from the `hearing` block of `/diagnostics/maturation.json` and from the panel's formatter. An operator cannot tell how far a stage is from its earliest or latest step.

Prior work found: `hearing-stage-saturation` (#601) made `HearingStageState` the single owner of stage and dwell in `state/lifecycle/hearing_stage.json`; `nexus-development-feed` (#582) added the `hearing` block and the panel row; `hearing-band-12h` (#574) and `hearing-stage-published` (#569) set the schedule and the event. None shows the dwell. The watch's `current` reading is only refreshed at a step, so its awake time is stale and cannot supply the dwell.

## What Changes

- `/diagnostics/maturation.json` `hearing` gains `dwell_seconds`, read from the owner file `state/lifecycle/hearing_stage.json` and returned only when the file names the same stage as the runtime reading (otherwise null), plus `min_dwell_seconds` and `max_dwell_seconds`.
- The cycle's runtime entry `hearing_stage` carries the two configured bounds (new `HearingStageWatch.runtime_reading` and `HearingStageState.params`). The published `development.hearing_stage` event and `current` are unchanged.
- The panel formatter appends the dwell, for example "stage 3 of 4, below 1732.1 Hz, 1.2 h of 1.5 to 7 h", and gives no dwell when the dwell or a bound is missing or the stage is 4.

## Capabilities

### Modified Capabilities

- `dashboard-observability`: the development panel shows the hearing stage's dwell.

## Impact

`kaine/dashboard/maturation.py`, `kaine/dashboard/static/dashboard_maturation.js`, `kaine/cycle/hearing_stage_watch.py`, `kaine/cycle/__main__.py`, `kaine/modules/audition/hearing_stage_state.py`, `docs/05-dashboard.md`, `docs/06-operation/development.md`, tests. Every new field is a number. The dashboard only reads the owner file and never writes it.
