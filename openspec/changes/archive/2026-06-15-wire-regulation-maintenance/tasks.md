## 1. Wire the event-driven trigger in Hypnos

- [x] 1.1 In `kaine/modules/hypnos/module.py` `_soma_consumer_loop`, in addition
      to the existing `soma.fatigue` + `crossed == true` trigger, ALSO trigger an
      early maintenance cycle on an event with `type == "soma.regulation"` AND
      `payload.get("action") == "request_maintenance"`.
- [x] 1.2 Reuse the SAME path the fatigue trigger uses
      (`_fatigue_triggered_enter_sleep` behind the `_sleep_lock.locked()` guard)
      so the non-interruptibility / freeze-preemption guards apply identically;
      keep it idempotent (no trigger if already sleeping).
- [x] 1.3 Log the regulation trigger distinctly (e.g. "soma.regulation
      request_maintenance — triggering regulation-driven maintenance").

## 2. Keep the engine flag as an advisory latch

- [x] 2.1 In `kaine/cycle/engine.py`, KEEP setting
      `self.maintenance_requested = True` on `request_maintenance` and keep its
      log line (no new coupling).
- [x] 2.2 Update the `consume_soma_regulation` docstring so the
      `request_maintenance` entry describes the flag as an advisory / diagnostic
      latch AND notes the real early-maintenance trigger is event-driven via
      Hypnos observing the regulation event on `soma.out`.

## 3. Docs

- [x] 3.1 Fix `docs/processes/cognitive-cycle.md` so the `request_maintenance`
      row describes the event-driven mechanism, not "Hypnos polls this".
- [x] 3.2 Fix `docs/processes/sleep-maintenance.md` so the regulation trigger is
      described as event-driven (Hypnos observes the `request_maintenance`
      regulation event on `soma.out`; the engine also latches an advisory
      `maintenance_requested` flag for diagnostics).

## 4. Tests

- [x] 4.1 New `tests/test_cycle_soma_regulation.py`: construct a `CycleEngine`
      with a fake bus/registry and assert `reduce_rate` lowers `_processing_rate`
      (clamped to bounds), `shed_module` calls
      `registry.request_shed_low_priority`, `request_maintenance` sets
      `maintenance_requested = True`, a missing `action` logs a warning and does
      not raise, and an unknown `action` is ignored without raising.
- [x] 4.2 New / extended Hypnos test: publishing a `soma.regulation` event with
      `action == "request_maintenance"` on `soma.out` triggers a maintenance
      sleep, mirroring the existing fatigue-trigger test.
- [x] 4.3 Run the full suite (`.venv/bin/pytest -q -p no:cacheprovider`) — all
      green.

## 5. Live validation (operator-supervised)

- [ ] 5.1 On an operator-supervised boot, drive Soma's regulator to publish a
      `soma.regulation` / `request_maintenance` advisory on `soma.out` and
      confirm Hypnos fires an earlier offline maintenance cycle through the
      guarded path (subject to freeze / not-already-sleeping guards), while the
      cycle engine's `maintenance_requested` flag latches `True` for diagnostics.
