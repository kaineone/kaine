## 1. Exposure record

- [ ] 1.1 The cycle writes `state/welfare/exposure.json` at shutdown in research mode, from the welfare producer's tally snapshot and the monitor's indicator counts, atomically with mode 0600, through the state encryptor when it is on. Tests: a stand-in tally and monitor give the expected record; a failed write logs at error level and does not change the exit code; a content check that every value is a number, boolean or table label.

## 2. Study runner

- [ ] 2.1 The runner copies the record into the step record and holds before the next step on a missing or unreadable record or any indicator crossing. Tests with stand-in step directories for the three spec scenarios.
- [ ] 2.2 `ack-welfare --step <line>/<k> --decision continue|stop-line` records the answer and releases or ends the line; `status` shows the hold. Tests: continue starts the next step on `run`; stop-line ends the line and keeps its preservations; neither touches the step's `state/`.
- [ ] 2.3 `analysis.py` prints the per-viewing exposure table. Test on synthetic step records.

## 3. Pilots

- [ ] 3.1 `kaine.experiment.calibrate` lists each pilot's exposure record in the settings record's input section and uses it for no setting. Test that derived values are unchanged with and without exposure records.

## 4. Docs and checks

- [ ] 4.1 The study chapter (the hold and `ack-welfare`), `docs/17-research-data/README.md` (the record's fields).
- [ ] 4.2 `openspec validate welfare-exposure-report --strict` passes.
- [ ] 4.3 Lead review of the PR.
