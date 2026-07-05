# Run completeness gating

## Why

`experiment-run-identity` gave every durable record a `run_id` and a per-sink
monotonic `seq`, and writes a `manifest.json` per run. But nothing yet *checks*
that a finished run's record is actually complete. A run can silently lose
records — a dropped tick, an observer that never wrote, a sink that shed records
under backpressure (`AsyncJsonlSink` drops the oldest entry when its queue is
full), or a corrupted line — and the data still *looks* clean: timestamps are
monotonic, files are present. An analyst grouping that run cannot tell a
complete dataset from a holey one. A holey run that reaches analysis produces
quietly-wrong results.

A finished run must be scannable for completeness before its data is trusted,
and an incomplete run must be reported inadmissible with the specific reasons.

## What Changes

- New boundary-neutral loader `kaine/experiment/run_records.py`: given a run id
  and the evaluation root, it reads every JSONL sink file, decrypts each line
  (`get_state_encryptor().decrypt_text`, tolerating both encrypted and plaintext
  lines), parses JSON, filters to that `run_id`, and groups records by source
  stream. A malformed line is counted as a parse error, never raised on.
- New `kaine/experiment/admissibility.py`:
  - `scan_run(run_id, *, root, expected_streams)` → `AdmissibilityReport`
    (`admissible`, `tick_gaps`, `seq_gaps`, `missing_streams`, `parse_errors`).
    `admissible` is true only when there are no tick gaps (the `cycle.tick`
    `tick_index` sequence is contiguous), no per-sink `seq` gaps, no missing
    expected streams, and no parse errors.
  - CLI `python -m kaine.experiment.admissibility <run_id>` prints the report
    and exits non-zero when inadmissible.
- `kaine/research/submission.py`: `build_research_bundle` accepts an optional
  `admissibility_run_id` + `expected_streams` and records an `admissibility`
  block (verdict + reasons) in the bundle manifest, so an inadmissible run can't
  reach analysis looking clean. The verdict is non-blocking by default; an
  opt-in `require_admissible=True` refuses to build an inadmissible bundle
  (`AdmissibilityError`). The expected-stream list is passed in as data, keeping
  `kaine.experiment` decoupled from the evaluation package.

## Impact

- Affected: new `kaine/experiment/run_records.py`, `kaine/experiment/admissibility.py`;
  light additive change to `kaine/research/submission.py`.
- Boundary-preserving: `kaine/experiment/` imports only stdlib + `kaine.security.crypto`;
  the expected-stream set is supplied by the caller, so the sidecar privacy
  boundary tests stay green.
- Ships safe: default callers (no `admissibility_run_id`) get unchanged
  behaviour; the gate is opt-in.
