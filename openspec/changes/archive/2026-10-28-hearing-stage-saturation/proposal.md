## Why

The hearing band widens on a fixed schedule: four equal steps over 12 awake hours. Offline, a band takes 5.1 to 5.7 hours to saturate from scratch, so a fixed three-hour spacing cuts learning short, and the gate's third condition (a floor of lived time) says nothing about whether the sensory schedule was lived through. The paper (A.7, Table A1) now releases each stage by ability: stage k ends when audition's own learning progress, restarted at the step, stays below lp_0 for W_sat = 600 awake seconds after at least d_min = 5400 awake seconds, or at d_max = 25200. Colour saturation is k/5 in stage k, and C3 becomes "the sensory schedule is complete".

## What Changes

- One owner of the stage: a persisted `HearingStageState` (kaine/modules/audition/hearing_stage_state.py). The hearing-stage watch drives it once a second from the shared awake-time provider and audition's learning progress read from the affect module; the audio stream, the visual source, the affect module (through the existing `development.hearing_stage` event) and the maturation gate read its stage and never compute one.
- Dwell persists across restarts, the saturation window restarts fresh after a restart, a missing learning-progress reading counts as unsaturated, and rests add no dwell because dwell advances only with awake time.
- `[perception_feed.stimulus_source.hearing]` gains `saturation_window_seconds`, `min_dwell_seconds` and `max_dwell_seconds`; `maturation_seconds` is retired (accepted with a warning).
- Colour saturation is k/5 in hearing stage k, replacing the exponential ramp; `colour_ramp_seconds` is retired (accepted with a warning) and its code default stays in the parameter record so the stimulus-source parameter digest is unchanged for the code default.
- C3 becomes "the sensory schedule is complete" (final stage reached); `[developmental_stage].min_lived_seconds` is retired (accepted with a warning). The study runner's 96-hour budget is unchanged.
- The maternal voice unlock is unchanged.

## Capabilities

### Modified Capabilities

- `developmental-stimulus`: stage advance by saturation, colour by stage.
- `developmental-stage`: C3 is schedule completion.

## Impact

- `kaine/modules/audition/hearing_band.py`, new `kaine/modules/audition/hearing_stage_state.py`, `kaine/cycle/hearing_stage_watch.py`, `kaine/modules/audition/feed.py`, `kaine/modules/vision/feed.py`, `kaine/modules/stimulus_source_signal.py`, `kaine/modules/perception_transition.py`, `kaine/boot/perception_feed.py`, `kaine/modules/affect/module.py`, `kaine/lifecycle/maturation_gate.py`, `kaine/lifecycle/gate_runner.py`, `kaine/cycle/__main__.py`, the dashboard's development panel, `config/kaine.toml`, docs.
- Behaviour: a developing entity's band steps arrive between 1.5 and 7 awake hours after the previous one, so the schedule runs 6 to 28 awake hours. Stage files from before this change carry no hearing stage; the first boot after it starts at stage 0 with no dwell.
