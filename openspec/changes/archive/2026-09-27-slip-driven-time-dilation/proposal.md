## Why

KAINE is meant to run the same mind on hardware from phones to servers, slower on weak hardware but with the same dynamics. When a tick takes longer than its period, the cycle starts the next tick immediately. The entity then gets fewer ticks per subjective second, while every clocked timer keeps running at full speed, so its dynamics distort: fatigue accumulates, dwell expires and drives decay between fewer ticks.

Lowering `[cycle].time_scale` fixes this, because the `EntityClock` dilates the tick period and every cognitive timer together. But only an operator can set it, by hand, and no profile does. On a Pixel 6a or an Orin Nano Super, the load that decides whether ticks fit changes by the minute, with sleep, speech and vision.

## What Changes

- A time-scale controller in the cycle, **off by default** (`[cycle].auto_time_scale = false`). When on, it measures how much of each tick's period the tick uses and lowers `time_scale` when ticks do not fit, so subjective time slows instead of distorting. It raises the scale back, never above the configured `time_scale`, when they fit again with room to spare.
  - It changes the scale only through the clock's re-anchoring setter, so subjective time stays continuous.
  - It moves down quickly and up slowly, with hysteresis and a minimum dwell between changes, and never below a configured floor.
  - It is disabled in deterministic cycle mode.
- **Honest records.** Each change publishes a `cycle.time_scale` event with the old and new scale, the measured utilization and the reason. `cycle.tick` payloads, ignition-log records and the run manifest carry the scale and the controller settings.
- **Film playback stays at real-time speed.** Under dilation a film runs faster in subjective time, and the records say so.
- **Study analysis.** The module-ignition analysis reports each step's time-scale range and flags a step whose scale changed. It also reports ignitions per tick alongside ignitions per film minute, so a dilated step is not mistaken for a change in the being.
- **Soma's regulation stays the entity's own.** Its `reduce_rate` still lowers the processing rate. That lowers utilization, and the controller may then raise the scale back toward the ceiling.

## Capabilities

### New Capabilities
- (none)

### Modified Capabilities
- `entity-time`: automatic, bounded, recorded dilation driven by measured tick utilization.
- `module-ignition-study`: the analysis accounts for dilation.

## Impact

- `kaine/cycle/engine.py` (utilization measurement and controller), a new `kaine/cycle/time_scale_controller.py`, `kaine/cycle/__main__.py` (wiring, manifest), `kaine/cycle/ignition_log.py`, `kaine/experiment/run_context.py`, `kaine/research/ignition_study/analysis.py`, `config/kaine.toml`, docs.
- Depends on `entity-clock-injection`: dilation is coherent only once every cognitive timer is on the entity clock.
