## 1. Phases
- [x] 1.1 `BootContext` (slotted) with one field per cross-phase value.
- [x] 1.2 26 phase functions in boot order, plus `_run_until_stopped` and `_shutdown`, extracted verbatim; `_boot_and_run` runs them.
- [x] 1.3 Check: inlining the phases back reproduces the original body's AST, apart from the one redundant import.

## 2. Tests
- [x] 2.1 Phase order, per-phase exit codes, declared fields, the runner's refusal, shutdown and escalation paths.
- [x] 2.2 The boot-order tests walk the phases through `tests/_boot_sequence.py`.

## 3. Follow-ups recorded
- [x] 3.1 Record construction-failure cleanup, early-exit order, late operator-sources validation, the unread MetricsCollector, repeated config reads, and moving the non-edge phases to their own modules.
