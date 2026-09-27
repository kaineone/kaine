## Context

`EntityClock.period(hz) = 1/(hz × scale)`, and its `scale` setter re-anchors so that subjective time is continuous. The engine measures each tick's wall duration and its target, and `pacing_stats()` averages them over a 32-tick window.

## Decisions

### What is measured
- **Busy time** is the wall time from a tick's start to the moment the loop is ready to sleep. It includes the control-event and Soma-regulation consumption that `wall_ms` omits today.
- **Utilization** `u = busy / period_wall`, where `period_wall = 1 / (processing_rate × scale)`. It is averaged with an exponential moving average whose time constant is `auto_time_scale_window_s` of wall time (default 30).
- Slip is not the signal. It is clipped at zero, so it cannot say when there is room to raise the scale again.

### The control law
- **Target.** Busy time is roughly independent of the scale while the period grows as the scale falls. The scale that brings utilization to its target `u*` (default 0.85) is therefore `s* = scale × u* / u`, clamped to `[auto_time_scale_floor, time_scale]` (floor default 0.1). The ceiling is the operator's configured `time_scale`, so automatic dilation only ever slows the mind down, never speeds it up.
- **Down.** When `u > u_high` (default 0.95) for at least `auto_time_scale_dwell_s` (default 10 s of wall time), the scale is set to `s*` in one step.
- **Up.** When `u < u_low` (default 0.6) for at least 3 × the dwell, the scale is raised by at most ×1.25, and not above `s*` or the ceiling.
- **Dwell.** No change within one dwell of the previous change.
- The asymmetry and the dead band between `u_low` and `u_high` prevent oscillation. That matters because a lower scale also lowers some tick costs, such as fewer camera frames per wall second.
- **Freeze** (scale 0) stays the freeze path; the controller never sets 0, and it does nothing while the cycle is frozen or the programme clock is held.
- **Deterministic mode** disables the controller, with an INFO log, because its decisions depend on wall timing.

### Where it lives
`kaine/cycle/time_scale_controller.py` is a pure class. It is fed `(busy_ms, now_wall)` once per tick by `run_forever` and returns a new scale or `None`. The engine applies a returned scale through `entity_clock.scale = …`, publishes `cycle.time_scale`, and records the change. The controller has no I/O, so it is unit-testable with a synthetic load.

### Records
- **`cycle.time_scale` event:** `{from, to, reason: "overload"|"headroom", utilization, window_s}`.
- **`cycle.tick` payload** gains `time_scale`.
- **The ignition log** records gain `time_scale`.
- **`RunContext`** gains `timing: {time_scale, auto_time_scale, floor, u_target, u_high, u_low, dwell_s, window_s}`.
- **The research event log** keeps `cycle.time_scale` events.

### Soma
Soma's regulation (`reduce_rate`) remains the entity's own response and is not suppressed. With `entity-clock-injection`, Soma's latency sense is subjective, so a well-dilated mind does not feel its slow hardware and rarely asks to slow down. If it does, the lower processing rate lowers utilization and the controller may raise the scale back toward the ceiling. The two effects compose; they do not fight.

### The film programme and the study
- The `PlaylistClock` stays on wall time, at real-time speed.
- For each step, the ignition analysis adds `time_scale_min`, `time_scale_max` and `time_scale_changed`, and `broadcasts_per_tick` alongside the per-film-minute rate.
- The report states that dilation lowers ignitions per film minute without any change in the being.
- The study runs with the controller off unless the operator turns it on for a slow host, and the manifest says which.

## Verification
- **Controller unit tests with synthetic busy times:**
  - Overload lowers the scale to `s*` after the dwell.
  - Headroom raises it slowly, capped at the ceiling.
  - No change inside the dead band.
  - No change within the dwell.
  - The floor holds.
  - No oscillation over a load that depends on the scale.
  - Deterministic mode disables it.
- **Engine test:** an injected slow tick drives the scale down, `cycle.time_scale` is published and the clock stays continuous.
- **Records:** tick payload, ignition-log records and run manifest.
- **Analysis:** a step with a scale change is flagged, and `broadcasts_per_tick` is reported.
