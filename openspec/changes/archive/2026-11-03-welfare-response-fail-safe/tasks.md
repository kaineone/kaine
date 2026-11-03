# Tasks

## 1. Stop-hook fallback

- [x] 1.1 A stop hook that raises makes the monitor place the welfare pause, record `pause_fallback` with `end_error`, and log at error level. Verify with the failed-hook test in `tests/test_preservation_monitors.py`.
- [x] 1.2 The failed-hook fallback pause re-arms after `override(["welfare"])`. Verify in `tests/test_welfare_response_rearms.py`.

## 2. Freeze that cannot be written

- [x] 2.1 `_place_welfare_freeze` never raises; it reports whether the freeze was written and keeps the unreadable-control-file flag as before.
- [x] 2.2 A failed freeze is recorded as `protective_action_freeze_failed` with `freeze_error`, the caretaker is notified, the response stays latched and the pause is not counted as placed.
- [x] 2.3 Later polls retry only the freeze, with a bounded error-log rate; a written freeze adds one `protective_action_freeze_placed` record and latches as a normal pause. Verify for the pause, no-hook and failed-hook branches in `tests/test_welfare_response_rearms.py`, with mutation checks on the retry and the records.

- [x] 2.4 The caretaker gets a distinct content-free `welfare_freeze_failed` notice (entity NOT paused, freeze retried) instead of `welfare_response`, and a `welfare_freeze_placed` notice when the pending freeze is placed. `on_response` receives the record's transition and the cycle maps it to the notice kind. Verify in `tests/test_caretaker.py`, `tests/test_caretaker_research_mode.py` and `tests/test_welfare_response_rearms.py`, with mutation checks on the mapping, the placed notice and the notice text.
- [x] 2.5 Each retry first reads the freeze holders; a `welfare` holder already in place counts as placed (one `protective_action_freeze_placed` record with `freeze_found_in_place`, no second freeze), and unreadable holders fall through to the normal retry. Verify with a freeze that writes and then raises once: no duplicate welfare entry, one placed record, and a later `override(["welfare"])` re-arms and is not undone.

## 3. Control file

- [x] 3.1 `write_control` leaves a corrupt control file unchanged and logs it once. Verify in `tests/test_cycle_freeze.py`.

## 4. Docs and checks

- [x] 4.1 `docs/11-preservation.md` describes the stop-hook fallback, the freeze retry, the already-placed check and the caretaker notices; the realistic freeze failures are a full disk or a control or lock file that cannot be opened (the lock blocks rather than fails).
- [x] 4.2 `openspec validate welfare-response-fail-safe --strict` passes.
