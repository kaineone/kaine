## Why

The cycle measured slip as the tick body's overrun of its budget, `max(0, wall - target)`. The time a tick period really takes also holds the work `run_forever` does after the tick and the oversleep of the pacing wait, and neither is in the body's wall time. In the tenth test boot `slip_ms` was 0 on 281,215 of 281,217 ticks while the cycle ran at 9.66 to 9.72 Hz against its 10 Hz target.

## What Changes

- `slip_ms` is measured from tick start to tick start: for each tick, how far the interval since the previous tick began exceeded that previous tick's budget. The first tick, and the first tick after a pause, report 0.
- `overrun_ticks` keeps its meaning, a tick whose own body exceeded its budget, and is now counted from `wall_ms > target_ms` directly.
- The scheduler is unchanged: the pacing wait is still the budget minus the body's wall time, and `wall_duration_ms`, `target_duration_ms`, the achieved-rate formula and the time-scale controller's inputs are as before.

## Capabilities

### Modified Capabilities

- `cognitive-cycle`: tick slip is measured from tick start to tick start.

## Impact

- `kaine/cycle/engine.py`, `docs/08-cognitive-cycle/README.md`, new `tests/test_cycle_slip_start_to_start.py`; `tests/test_cycle_rates.py`, `tests/test_cycle_pacing_report.py` and `tests/test_deterministic_cycle.py` follow the new measurement.
- Behaviour: none for the entity. Slip feeds only the `cycle.tick` event, the pacing report, the research log and plugin tick observers; no module reads it. The interoception module reads `wall_duration_ms`, which is unchanged.
