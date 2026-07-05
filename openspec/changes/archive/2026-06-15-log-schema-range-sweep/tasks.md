# Tasks

## 1. declarative schema
- [x] 1.1 `kaine/experiment/log_schema.py` — per-event-type `SCHEMA` + generic per-field `FIELD_RANGES` of physically-possible ranges, taken from the producing modules + research taxonomy.
- [x] 1.2 Use `NONNEG` (`>= 0`) where no hard upper bound is defined; omit fields with no defined bound (e.g. `expected_free_energy`) rather than guessing.
- [x] 1.3 Handle the nested coherence PLV dict (`coherence[pair] ∈ [0, 1]`) specially.

## 2. sweep
- [x] 2.1 `sweep_run(run_id, *, root)` → list of `Violation` (`stream`, `field`, `value`, `bound`, `event_type`, `seq`), reusing `run_records.py` (decrypt + parse). Fail-closed: any out-of-range value is a violation.
- [x] 2.2 CLI `python -m kaine.experiment.log_schema <run_id>` prints violations, exits non-zero if any.

## 3. tests + docs
- [x] 3.1 Tests: in-range records → no violations; negative `prediction_error` → violation; `valence=2.0` → violation; `confidence=1.5` → violation; multiple violations in one record; coherence PLV out of range; generic field-range off-taxonomy; decrypt round-trip; CLI exit codes.
- [x] 3.2 Docs: present-tense section on log range validation under `docs/`.
- [x] 3.3 `openspec validate log-schema-range-sweep --strict`.
