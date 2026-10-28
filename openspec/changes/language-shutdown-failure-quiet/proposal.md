## Why

In the 13th test boot (2026-10-27) the test script stopped the whole compose stack at once. The model server went away while the language module had a think request in flight. Six seconds after "signal received; shutting down" the language module logged ERROR "language failed to realize think intent" with a full traceback (an httpx name-resolution failure, chained). An operator stopping the stack does the same, so a clean shutdown leaves an error trace that looks like a fault.

## What Changes

- When a realization fails after the cycle's stop event is set (or the module's own stop flag is set), the language module logs one WARNING line naming the intent kind and the exception class, with no traceback. A failure while running still logs ERROR with the traceback.
- The content-free `realization_failed` audit record is written in both cases, unchanged (mode and reason class only).
- Signal: the module's own `_stopped` flag is set only in `_shutdown_modules`, the last step of `_shutdown`, after the cycle, the caretaker, the sidecar and the final checkpoint, so it is not yet set when the in-flight request fails. The cycle's stop event is set by the signal handler at once. The module gets that one event through a new `set_stop_event` setter, called from the boot's signal phase, the same kind of seam as `set_expects_self_model`. No global is added.
- The supervisor's heavy-restart closure (`_make_rebuild_module`) takes a `stop_event_source` callable, read at rebuild time because the event is created in a later boot phase, and gives the event to a rebuilt module that has `set_stop_event`.
- Not changed: other modules with network calls are listed in the PR and left alone.

## Capabilities

### Modified Capabilities

- `language`: a realization failure during shutdown is logged as one line, not as an error trace.

## Impact

- `kaine/modules/language/module.py`, `kaine/cycle/__main__.py` (one wiring call), `tests/test_language_module.py`.
- No config, stream or audit schema changes.
