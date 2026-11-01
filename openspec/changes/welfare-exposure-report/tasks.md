## 1. Exposure record

- [x] 1.1 The cycle deletes `state/welfare/exposure.json` at boot, before the gates. Test: a boot over a state tree that holds one leaves none behind, including when the boot is then refused by a gate.
- [x] 1.2 The cycle writes the record at shutdown in research mode: `run_id`, `boot_started_at`, indicator figures from the welfare monitor's evaluator, shares with `producer_restarts` and `covered_awake_seconds` from the producer's tally; plain JSON, atomic, mode 0600. Tests: stand-in monitor and tally give the expected record; a restarted producer is reflected in the coverage fields while the indicator figures cover the whole run; a failed write logs at error level and does not change the exit code; a content check that every value is a number, boolean, the run id, a timestamp or a table label.

## 2. Study runner

- [x] 2.1 The runner copies a valid record into the step record and holds before the next step on a missing, unreadable, mismatched or incomplete record, or any indicator crossing. Tests with stand-in step directories for every spec scenario, including a crash after a revive whose bundle held an old record.
- [x] 2.2 `ack-welfare --step <line>/<k> --decision continue|stop` records the answer and releases the hold or ends the line; `status` shows the hold. Tests: continue starts the next step on `run`; stop ends the line and keeps its preservations; neither touches the step's `state/`.
- [x] 2.3 `analysis.py` prints the per-step exposure table. Test on synthetic step records.

## 3. Docs and checks

- [x] 3.1 The study chapter (the hold and `ack-welfare`), `docs/17-research-data/README.md` (the record's fields, its binding and its plain-JSON format).
- [x] 3.2 `openspec validate welfare-exposure-report --strict` passes.
- [ ] 3.3 Lead review of the PR.
