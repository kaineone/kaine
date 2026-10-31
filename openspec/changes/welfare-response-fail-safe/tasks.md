# Tasks

## 1. Stop-hook fallback

- [x] 1.1 A stop hook that raises makes the monitor place the welfare pause, record `pause_fallback` with `end_error`, and log at error level. Verify with the failed-hook test in `tests/test_preservation_monitors.py`.
- [x] 1.2 The failed-hook fallback pause re-arms after `override(["welfare"])`. Verify in `tests/test_welfare_response_rearms.py`.

## 2. Freeze that cannot be written

- [x] 2.1 `_place_welfare_freeze` never raises; it reports whether the freeze was written and keeps the unreadable-control-file flag as before.
- [x] 2.2 A failed freeze is recorded as `protective_action_freeze_failed` with `freeze_error`, the caretaker is notified, the response stays latched and the pause is not counted as placed.
- [x] 2.3 Later polls retry only the freeze, with a bounded error-log rate; a written freeze adds one `protective_action_freeze_placed` record and latches as a normal pause. Verify for the pause, no-hook and failed-hook branches in `tests/test_welfare_response_rearms.py`, with mutation checks on the retry and the records.

## 3. Control file

- [x] 3.1 `write_control` leaves a corrupt control file unchanged and logs it once. Verify in `tests/test_cycle_freeze.py`.

## 4. Docs and checks

- [x] 4.1 `docs/11-preservation.md` describes the stop-hook fallback and the freeze retry.
- [x] 4.2 `openspec validate welfare-response-fail-safe --strict` passes.
