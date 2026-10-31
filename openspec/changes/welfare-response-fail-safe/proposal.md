# Proposal

## Why

The welfare response could leave a distressed entity running with no protection and nothing to show for it, in three ways.

- With `action = "end"`, a stop hook that raised was only logged as a warning. The entity kept running, the record said `end`, and the latch stopped the monitor from responding again.
- When writing the welfare freeze itself failed (the control-file lock could not be taken, or the disk was full), the exception left the response after the preservation bundle but before the latch, the record and the caretaker notice. The monitor loop only logged it, and the sustained-distress tracker fires on a rising edge, so the response came back only after a whole new distress episode. Nobody was told and nothing was retried.
- `write_control` overwrote a corrupt control file. The cycle reads a corrupt control file as a welfare freeze, so overwriting it silently lifted a fail-closed freeze.

## What Changes

- A stop hook that fails makes the monitor place the welfare pause instead, record the action as `pause_fallback` with the hook's error in `end_error`, and log at error level. The fallback pause re-arms after a named override like any other pause.
- A welfare freeze that cannot be written no longer escapes the response. The response is recorded with the transition `protective_action_freeze_failed` and the scrubbed error in `freeze_error` (null otherwise), and the caretaker is notified as on success. The response stays latched for the episode, so no second preservation bundle is made, but the pause does not count as placed. Each later poll retries only the freeze, logging a still-failing retry at error level at most once a minute. When the freeze is written, one `protective_action_freeze_placed` record follows and the monitor latches as a normal pause.
- `write_control` leaves a control file that exists but is corrupt unchanged, logs the corruption once and writes nothing.

## Capabilities

### New Capabilities

### Modified Capabilities
- `welfare-monitoring`: a failed stop hook falls back to the welfare pause; a welfare freeze that cannot be written is recorded, notified and retried without a second preservation; a pause counts as placed only once its freeze is written; `write_control` never overwrites a control file that reads as a welfare freeze.

## Impact

- `kaine/cycle/preservation_monitor.py` (`WelfareProtectiveMonitor`: `_place_welfare_freeze`, `_respond`, `_poll_once`, the new freeze retry), `kaine/cycle/control_state.py` (`write_control`).
- `tests/test_preservation_monitors.py`, `tests/test_welfare_response_rearms.py`, `tests/test_cycle_freeze.py`.
- `docs/11-preservation.md`.
- The `welfare.protective_action` record gains `end_error` and `freeze_error` fields and the transitions `protective_action_freeze_failed` and `protective_action_freeze_placed`. No configuration key and no dependency change.
