# Tasks

## 1. shared loader
- [x] 1.1 `kaine/experiment/run_records.py` — `load_run_records(run_id, *, root)` reads every JSONL sink file, decrypts each line (encrypted + plaintext), parses JSON, filters to `run_id`, groups by stream; malformed line → parse-error count, never raises.
- [x] 1.2 Skip the `runs/` manifest dir; derive stream name from the `<name>-<UTC-date>.jsonl` sink file name.

## 2. admissibility scan
- [x] 2.1 `kaine/experiment/admissibility.py` — `AdmissibilityReport` dataclass (`admissible`, `tick_gaps`, `seq_gaps`, `missing_streams`, `parse_errors`) + `reasons()`.
- [x] 2.2 `scan_run(run_id, *, root, expected_streams)` — contiguity check on `cycle.tick` `tick_index`, per-sink `seq` contiguity, missing-stream detection, parse-error rollup; `admissible` true only when all clean.
- [x] 2.3 CLI `python -m kaine.experiment.admissibility <run_id>` prints the report, exits non-zero when inadmissible.

## 3. bundle integration
- [x] 3.1 `build_research_bundle` accepts `admissibility_run_id` + `expected_streams`; records an `admissibility` block (verdict + reasons) in the bundle manifest.
- [x] 3.2 Opt-in `require_admissible=True` raises `AdmissibilityError` (and leaves no partial bundle) on an inadmissible run; default is non-blocking.
- [x] 3.3 Keep the expected-stream list a caller-supplied data argument (no evaluation import); confirm the two boundary tests stay green.

## 4. tests + docs
- [x] 4.1 Tests: complete run → admissible; tick gap → inadmissible; seq gap → inadmissible; missing stream → inadmissible; parse error → inadmissible; loader run-filter/grouping; runs-dir skip; decrypt round-trip (AsyncJsonlSink encryption on → read back); CLI exit codes; submission manifest verdict (admissible/inadmissible/absent/strict-refuse).
- [x] 4.2 Docs: present-tense section on run completeness gating under `docs/`.
- [x] 4.3 `openspec validate run-completeness-gating --strict`.
