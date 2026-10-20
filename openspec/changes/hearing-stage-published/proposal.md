## Why

The hearing band's stage is computed per audio block inside the stimulus-source audio producer thread and is never logged or published. An operator watching a boot, or reading its logs afterwards, cannot tell which band the entity hears, and an analysis cannot line a change in the audition module's errors up with the step that caused it.

## What Changes

- A hearing-stage watch reads the same awake-time provider the audio stream reads, once a second, and calls the same pure `hearing_stage` and `band_edges` functions. On the first reading and on every change of stage it logs an INFO line and publishes `development.hearing_stage` on `development.out` with the stage, the previous stage, the band edges and the awake time.
- A failed publish is retried on the next reading. After stage 4, the open band, the watch stops.
- The watch runs in the stimulus-source presence task, only in stimulus-source mode with the audition module and the hearing band enabled.
- The stage clock, the filter and the audio are unchanged. `development.out` is not a module stream, so the event never enters the workspace.

## Capabilities

### Modified Capabilities

- `developmental-stimulus`: the hearing band's stage transitions are logged and published.

## Impact

- New `kaine/cycle/hearing_stage_watch.py`, `kaine/cycle/__main__.py` (`_start_stimulus_source_presence`), `docs/06-operation/development.md`, new `tests/test_hearing_stage_watch.py`.
- Behaviour: none for the entity. The log gains one line per stage, at most five per entity, and `development.out` one event per stage.
