## Why

Build prompt §7.1 names variable-speed cognition as the first emergent
capability: "Cycle rate as runtime parameter. Separate processing rate
from experiential broadcast rate. Test at various ratios." The cycle
already supports this from Phase 1.2 (`set_processing_rate`,
`set_experiential_rate`, the float experiential accumulator) and has
unit tests against fake clocks. Phase 7.1 closes the capability by
adding a bus-driven control surface so other modules can request
rate changes at runtime, and verifying behavior at the additional
ratios the paper highlights (paper §4.1: decelerated operation for
processes "below human temporal resolution").

## What Changes

- Add a `cycle.control` consumer task to `CognitiveCycle`. When an
  event lands on `cycle.control` with type
  `cycle.set_rates`, the cycle updates `processing_rate_hz` and/or
  `experiential_rate_hz` from the payload (whichever fields are
  present). After the update, the cycle publishes a `cycle.rates`
  event reflecting the new state.
- Add tests covering: rate change via bus event; pause/resume
  hooks still fire after a rate change; experiential ratios at
  three new ratios (3:1, 7:3, 100:1) verifying broadcast counts.
- Existing tests in `tests/test_cycle_rates.py` already exercise the
  direct API; this change adds the bus-driven path.

## Capabilities

### Modified Capabilities

- `cognitive-cycle`: adds a bus-driven rate-control surface. The
  cycle now subscribes to a `cycle.control` stream and accepts
  `cycle.set_rates` events that update its `processing_rate_hz` and
  `experiential_rate_hz`. The existing `set_processing_rate` and
  `set_experiential_rate` direct-API methods remain.

### New Capabilities

None.

## Impact

- **Repo:** updates `kaine/cycle/engine.py` (consumer task + publish
  cycle.rates), adds `tests/test_cycle_runtime_control.py`.
- **No new external deps.**
- **No runtime impact** until the cycle is actually running.
