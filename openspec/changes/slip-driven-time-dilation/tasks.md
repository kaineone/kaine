## 1. Controller

- [ ] 1.1 `kaine/cycle/time_scale_controller.py`: the control law (EMA utilization, down/up thresholds, dwell, floor and ceiling), pure and unit-tested.
- [ ] 1.2 Engine: busy-time measurement including control and regulation consumption; the controller fed per tick; scale applied through the clock setter; disabled in deterministic mode.
- [ ] 1.3 `[cycle]` keys (`auto_time_scale`, `auto_time_scale_floor`, `auto_time_scale_target`, `auto_time_scale_high`, `auto_time_scale_low`, `auto_time_scale_dwell_s`, `auto_time_scale_window_s`) with validation; shipped off.

## 2. Records

- [ ] 2.1 `cycle.time_scale` event; `time_scale` in `cycle.tick` payloads and ignition-log records; timing settings in `RunContext`; research event log keeps the events.
- [ ] 2.2 Ignition analysis: per-step scale range, `time_scale_changed`, `broadcasts_per_tick`; the report's note on dilation.

## 3. Docs and verification

- [ ] 3.1 Docs: the timing page, configuration, deployment tiers, and the study operations section.
- [ ] 3.2 Offline suite green; `openspec validate slip-driven-time-dilation --strict`.
