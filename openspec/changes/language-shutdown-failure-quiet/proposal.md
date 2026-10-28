## Why

In the 13th test boot (2026-10-27) the test script stopped the whole compose stack at once. The model server went away while the language module had a think request in flight. Six seconds after "signal received; shutting down" the language module logged ERROR "language failed to realize think intent" with a full traceback. An operator stopping the stack does the same, so a clean shutdown leaves an error trace that looks like a fault.

Research (`.claude/ops/final-utterance-at-shutdown-2026-10-28.md`, Option A) shows the condition is not that the server vanished but that a stop has begun. A stop is an interruption, as when speech is cut at loss of responsiveness in anaesthesia or sleep onset: the utterance is dropped and not remembered. Three paths treat the utterance differently today: a failure logs ERROR, a module-shutdown cancel loses it with no record, and an utterance that finishes between the stop signal and module shutdown (the language module keeps running until the modules shut down, after the evaluation sidecar and run recorder have stopped) is logged and published late.

## What Changes

- Signal: the cycle's stop event, given to the module by `Language.set_stop_event()` from the boot's signal phase and from the supervisor's heavy-restart closure (`stop_event_source`, read at rebuild time), or the module's own `_stopped`. The module's own flag alone is set too late (only in `_shutdown_modules`, the last shutdown step).
- Once a stop has begun, a generation that fails is logged as one INFO line with no traceback. A generation cancelled by the module's shutdown (`_cancel_gen_task`, or the outer cancel in `_settle_gen_task`) is treated the same. An answer that arrives after the stop began is discarded: nothing reaches the intent log or the bus.
- For external speech only, the module writes a content-free `interrupted_by_stop` record (`mode`, `reason_class`) to `language.internal`. It replaces `realization_failed` when a stop has begun. A think leaves no record.
- A failure while running is unchanged: ERROR with the traceback and the `realization_failed` record.
- Docs: the language module page lists the new record.

## Capabilities

### Modified Capabilities

- `language`: a stop interrupts the utterance in flight; the interruption record.

## Impact

- `kaine/modules/language/module.py`, `kaine/cycle/__main__.py`, `tests/test_language_module.py`, `docs/09-modules/language.md`.
- The sleep ignition audit ignores the new record type (it counts only `realization_failed`).
