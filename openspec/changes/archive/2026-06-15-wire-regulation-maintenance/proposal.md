## Why

The `soma-predictive` spec's scenario "request_maintenance flags Hypnos"
(requirement "Cycle engine drains soma.regulation advisorily") says: when the
cycle engine receives a `soma.regulation` event with
`action == "request_maintenance"`, "a maintenance-requested flag is set that
Hypnos reads to schedule an earlier offline cycle."

In reality this linkage is unimplemented. `CycleEngine.consume_soma_regulation`
sets `self.maintenance_requested = True`, but nothing ever reads that flag.
Hypnos schedules an early maintenance cycle only off `soma.fatigue` crossings
in `_soma_consumer_loop`. The `request_maintenance` → Hypnos linkage is a dead
flag, and the entire `consume_soma_regulation` consumer is untested. Two process
docs also wrongly claim "Hypnos polls this" flag.

## What Changes

- Hypnos's `_soma_consumer_loop` SHALL ALSO trigger an early maintenance cycle
  when it observes a `soma.regulation` event with
  `action == "request_maintenance"` on `soma.out`, reusing the exact guarded
  path the fatigue trigger uses (so non-interruptibility / freeze / not-already-
  sleeping guards apply identically). The linkage is event-driven with no new
  Hypnos → cycle-engine coupling.
- The cycle engine SHALL keep latching `self.maintenance_requested = True` on a
  `request_maintenance` advisory, but it is now documented as an advisory /
  diagnostic latch only — nothing reads it to drive behaviour.
- The `soma-predictive` spec scenario "request_maintenance flags Hypnos" SHALL
  be reworded to the event-driven mechanism.
- The `consume_soma_regulation` consumer SHALL gain real test coverage, and a
  Hypnos test SHALL prove the regulation-driven maintenance trigger fires.
- Process docs (`cognitive-cycle.md`, `sleep-maintenance.md`) SHALL be corrected
  to describe the event-driven mechanism rather than flag polling.

## Capabilities

### New Capabilities

<!-- none -->

### Modified Capabilities

- `soma-predictive`: reword the "request_maintenance flags Hypnos" scenario of
  the "Cycle engine drains soma.regulation advisorily" requirement so the early
  maintenance trigger is event-driven (Hypnos observes the
  `soma.regulation` / `request_maintenance` event on `soma.out`), and the
  engine's `maintenance_requested` flag is an advisory / diagnostic latch.

## Impact

- **Code**: `kaine/modules/hypnos/module.py` (`_soma_consumer_loop`),
  `kaine/cycle/engine.py` (docstring on `consume_soma_regulation` only — no
  behaviour change; flag remains latched).
- **Docs**: `docs/processes/cognitive-cycle.md`,
  `docs/processes/sleep-maintenance.md`.
- **Tests**: new `tests/test_cycle_soma_regulation.py`; new Hypnos
  regulation-trigger test alongside the existing fatigue-trigger tests.
- **Operator procedure**: a live, operator-supervised boot check that a
  `request_maintenance` advisory actually fires an earlier offline cycle.
