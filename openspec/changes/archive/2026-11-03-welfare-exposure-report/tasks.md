## 1. Exposure record

- [x] 1.1 The cycle deletes `state/welfare/exposure.json` at boot, before the gates. Test: a boot over a state tree that holds one leaves none behind, including when the boot is then refused by a gate.
- [x] 1.2 The cycle writes the record at shutdown in research mode: `run_id`, `boot_started_at`, indicator figures from the welfare monitor's evaluator, shares with `producer_restarts` and `covered_awake_seconds` from the producer's tally; plain JSON, atomic, mode 0600. Tests: stand-in monitor and tally give the expected record; a restarted producer is reflected in the coverage fields while the indicator figures cover the whole run; a failed write logs at error level and does not change the exit code; a content check that every value is a number, boolean, the run id, a timestamp or a table label.

- [x] 1.3 The monitor's awake time is also counted in wall seconds (`awake_wall_seconds`, the spans' awake entity seconds divided by the time scale per poll; null when the scale cannot be read), and the runner compares the tally's coverage against it. Tests: the real monitor, tally, writer and reader at time scale 1 and 2 give no coverage hold; an unreadable scale leaves the count null; a record without the count, or a short tally under dilation, holds.

- [x] 1.4 `indicator_poll_failures` and `non_default_settings` in the monitor's part of the record; the runner holds for incomplete coverage on any indicator poll failure. Tests in `tests/test_welfare_exposure_record.py` and `tests/test_ignition_study_welfare_hold.py`.

## 2. Study runner

- [x] 2.1 The runner copies a valid record into the step record and holds before the next step on a missing, unreadable, mismatched or incomplete record, or any indicator crossing. Tests with stand-in step directories for every spec scenario, including a crash after a revive whose bundle held an old record.
- [x] 2.2 `ack-welfare --step <line>/<k> --decision continue|stop` records the answer and releases the hold or ends the line; `status` shows the hold. Tests: continue starts the next step on `run`; stop ends the line and keeps its preservations; neither touches the step's `state/`.
- [x] 2.4 A protective response holds: the runner holds with `protective_response` whenever the monitor's `responses` is not empty or is not a dict. Tests: the `action = "end"` boot with an `indicators_unavailable` response and no rest or freeze holds; a malformed response count holds; a clean monitor does not.
- [x] 2.5 A failed step's hold: `--retry-failed` refuses (exit 4) while the failed record's unanswered hold names `indicator_crossing` or `protective_response`; `ack-welfare` answers a failed step; `stop` on a failed step ends its line and the step is never retried; `status` and the halt message show the hold; a record missing after a crash is shown and does not block the retry. Tests in `tests/test_ignition_study_welfare_hold.py`.
- [x] 2.6 A `failed:critical` step's exposure is read once its cycle has exited, before a retry or an answer (`_resolve_critical_exposure`), and the step is recorded again with it; any hold reason on a critical step blocks the retry; every boot first copies an existing record to `welfare_exposure_archive/`. Tests: the real writer and reader for a boot that crossed then failed critical (hold, retry refused, answer releases); a critical step with no record holds; a running cycle is not read; the archive copy; the existing critical-retry test now answers the `missing` hold before the retry.
- [x] 2.7 Tests for the guards the second review found untested, each shown to kill its mutant: the copy before a boot (N11), the refusal when the copy fails (N12), an unknown hold reason (N22) and an empty or unreadable reasons list (N24) blocking a retry; the stop-event guard on the welfare-monitor liveness check across the run loop's await (N16) is in `tests/test_welfare_monitor_liveness.py`.
- [x] 2.3 `analysis.py` prints the per-step exposure table. Test on synthetic step records.

## 3. Docs and checks

- [x] 3.1 The study chapter (the hold and `ack-welfare`), `docs/17-research-data/README.md` (the record's fields, its binding and its plain-JSON format).
- [x] 3.2 `openspec validate welfare-exposure-report --strict` passes.
- [x] 3.3 Lead review of the PR.
