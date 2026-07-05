# Process: Run Admissibility (Completeness Gating + Log Validation)

After a cycle run finishes, two offline checks decide whether its data is
trustworthy for analysis. Completeness gating proves the run's record is
*whole*; log validation proves its numbers are *physically plausible*. Together
they form the post-run admissibility layer that sits on top of
[run identity](run-identity.md): every durable record already carries a `run_id`
and a per-sink monotonic `seq`, and each run has a `manifest.json`.

Both checks are read-only and never run from the cognitive cycle. They are
operator/analysis tools (and a hook in the research bundle builder).

Related: [run-identity.md](run-identity.md) ·
[research-operation.md](research-operation.md) ·
[testing-framework.md](testing-framework.md) ·
[../research-participation.md](../research-participation.md)

---

## Shared record loader

`kaine.experiment.run_records.load_run_records(run_id, *, root)` walks every
JSONL sink file under the evaluation root, decrypts each line
(`get_state_encryptor().decrypt_text`, which transparently passes plaintext
through when encryption is off), parses the JSON, keeps the records carrying the
target `run_id`, and groups them by source stream (the sink file's `<name>`
prefix). A line that cannot be decrypted or parsed is counted as a parse error,
never raised on — a corrupt record is itself a signal. The `runs/` manifest
directory is skipped (it holds `manifest.json`, not record streams).

The loader imports only the standard library and `kaine.security.crypto`. It
never imports the evaluation package: callers that need the set of *expected*
streams supply it as data.

## Completeness gating

`kaine.experiment.admissibility.scan_run(run_id, *, root, expected_streams)`
returns an `AdmissibilityReport`. A run is **admissible** only when all four hold:

- **Contiguous cycle ticks.** `cycle.tick`'s `tick_index` runs `0, 1, 2, …`. A
  gap (`tick_gaps`) means ticks went missing.
- **Contiguous per-sink `seq`.** Each stream's `seq` is contiguous. A gap
  (`seq_gaps`, per stream) means records were silently dropped — invisible from
  timestamps alone (`AsyncJsonlSink` sheds its oldest entry under backpressure).
- **All expected streams present.** Any stream in `expected_streams` that
  produced zero records this run is listed in `missing_streams` (a silent
  observer failure).
- **No parse errors.** Any unparseable line is counted in `parse_errors`.

`report.reasons()` summarizes why a run failed. The CLI

```
python -m kaine.experiment.admissibility <run_id> [--root DIR] [--expected-stream NAME ...] [--json]
```

prints the report and exits non-zero when the run is inadmissible.

### Bundle integration

`kaine.research.submission.build_research_bundle` runs BOTH the completeness
gate (`scan_run`) and the log-range sweep (`sweep_run`) over the run(s) present
in `eval_root` and records both verdicts in the bundle manifest, so an
inadmissible run cannot reach analysis looking clean.

`require_admissible` **defaults to `True`**: an inadmissible run — failing
either check — is **blocked from export by default** (`AdmissibilityError` is
raised and no partial bundle is left behind). This is the safe default; passing
`require_admissible=False` is what turns the gate into a non-blocking
annotation instead.

The run(s) to gate are **auto-discovered**, not limited to a single passed-in
run id: `discover_run_ids` scans every `*.jsonl` sink file under the whole
`eval_root` tree and gates every distinct `run_id` it finds there, so the
guarantee holds at the real operator entry point (`python -m kaine.research`)
even when no run id is passed. `admissibility_run_id` is optional and only
*narrows* the gate to one pinned run — it does not replace discovery: any other
run_id still found under `eval_root` and not explicitly acknowledged via
`admissibility_related_run_ids` is folded in as a restart/multi-process signal
(see below), and a pin that matches zero discovered records is itself
inadmissible.

#### Restart / multi-process detection

A finished run's completeness scan also treats a restart or overlapping
process as inadmissible, via two signals on `AdmissibilityReport`:

- `restart_seq_resets` — maps a stream name to the `seq` values observed AFTER
  a backward jump in that stream's raw (unsorted) `seq` sequence. A per-sink
  `seq` is a single process's monotonic counter; a later value that drops back
  below the running maximum (typically to 0) means a fresh `AsyncJsonlSink`
  instance started stamping again — i.e. the process restarted mid-run without
  minting a new `run_id`. This is invisible to the contiguity check, which
  treats `seq` as a set and tolerates duplicates.
- `related_run_ids` — additional `run_id`s the operator (or the bundle builder,
  via auto-discovery) declares as a continuation of the same logical run, e.g.
  a crash/resume where the resumed process minted a fresh `run_id` (a fresh
  `RunContext` never reuses one). `scan_run(run_id, ..., related_run_ids=...)`
  merges their records into the scan by stream; declaring ANY related run id is
  itself a restart/multi-process signal, so a non-empty `related_run_ids`
  always makes the run inadmissible.

The `python -m kaine.experiment.admissibility <run_id>` CLI exposes this as a
repeatable `--related-run-id RUN_ID` flag for standalone completeness scans.

#### Override escape hatch

There is one explicit, operator-only way to export a run that failed
admissibility: pass `admissibility_override=True` **and** a non-empty
`admissibility_override_reason`. Both are required together — a bare
`admissibility_override=True` with an empty or blank reason raises
`AdmissibilityOverrideError` before anything is built, so the override can
never fire by accident. When used correctly, the manifest records an
`admissibility_override` block (`overridden: true` plus the reason) so an
overridden export can never be mistaken for a clean one. The `python -m
kaine.research` CLI surfaces this as `--admissibility-override-reason "<why>"`.

#### Range admissibility in the manifest

Alongside the `admissibility` block, the bundle manifest carries a
`range_admissibility` block: the log-range sweep (`sweep_run`) run over every
run_id in the logical run (the primary run plus any `related_run_ids`), giving
`admissible` (bool) and the list of `violations` found across all of them. This
is what lets an out-of-range value in a restarted/related run block the export
even when the primary run's own numbers are clean.

## Log range validation

`kaine.experiment.log_schema.sweep_run(run_id, *, root)` re-checks the run's
logged numbers against a declared schema of physically-possible ranges and
returns a list of `Violation`s (`stream`, `field`, `value`, `bound`,
`event_type`, `seq`). It is fail-closed: any out-of-range value is a violation;
an empty list means every declared field is within range. The CLI

```
python -m kaine.experiment.log_schema <run_id> [--root DIR] [--json]
```

prints violations and exits non-zero if any exist.

The ranges are taken from the producing modules and the research event taxonomy.
Where a field has no well-defined hard upper bound it uses a generic `>= 0`
(`NONNEG`); where a field has no defined bound at all it is omitted rather than
guessed (an honest "no rule", not a silent pass).

### Declared ranges

| Field | Range | Source |
| --- | --- | --- |
| `salience` | `[0, 1]` | bus schema (`Field(ge=0.0, le=1.0)`) |
| `prediction_error` | `[0, ∞)` | clamped `max(0.0, e)` at the soma producer |
| coherence PLV (per pair) | `[0, 1]` | phase-locking value |
| `valence` | `[-1, 1]` | thymos affect state |
| `arousal` | `[0, 1]` | thymos affect state |
| `dominance` | `[-1, 1]` | thymos affect state |
| `confidence` | `[0, 1]` | nous (`1 - normalised_entropy`, clamped) |
| drive `value` | `[0, 1]` | thymos drives |
| `familiarity_scalar` | `[0, 1]` | empatheia |
| `wellness`, `fatigue_value` | `[0, 1]` | soma report |
| `error_magnitude`, `phantasia.world_error.error` | `[0, ∞)` | non-negative magnitudes |

Omitted as undefined: `expected_free_energy` (a signed scalar with no documented
range), and latency / elapsed / duration / count fields beyond the generic
non-negative case.
