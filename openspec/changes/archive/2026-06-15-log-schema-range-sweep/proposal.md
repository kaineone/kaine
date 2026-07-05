# Log schema range sweep

## Why

The system's numeric records have well-defined physical ranges: a probability is
in `[0, 1]`, a prediction error is non-negative, an affect valence is in
`[-1, 1]`, a phase-locking coherence value is in `[0, 1]`. Producers clamp these
at write time, but nothing re-checks them after the fact. If a clamp regresses,
a unit changes, or a record is corrupted, a physically-impossible number can sit
in the logs and skew any downstream analysis without ever being noticed. The
admissibility gate (`run-completeness-gating`) proves a run is *complete*; it
does not prove the values are *plausible*.

A finished run's logged numbers must be re-validatable offline against declared
physical ranges, and any out-of-range value must be reported as a violation
(fail-closed).

## What Changes

- New `kaine/experiment/log_schema.py`:
  - A declarative per-event-type schema of physically-possible ranges plus a
    generic per-field range table, both taken from the producing modules and the
    research event taxonomy. Fields with no well-defined hard bound use a generic
    `>= 0` (`NONNEG`) or are omitted rather than guessed.
  - `sweep_run(run_id, *, root)` → list of `Violation`
    (`stream`, `field`, `value`, `bound`, `event_type`, `seq`), reusing
    `kaine/experiment/run_records.py` (decrypt + parse). Any out-of-range value
    is a violation; an empty list means the run's logged values are all within
    range.
  - CLI `python -m kaine.experiment.log_schema <run_id>` prints violations and
    exits non-zero if any.
- Reuses the boundary-neutral loader from `run-completeness-gating`; no new
  coupling to the evaluation package.

## Declared ranges

- `salience ∈ [0, 1]` (bus schema `Field(ge=0.0, le=1.0)`)
- `prediction_error ≥ 0` (clamped `max(0.0, e)` at the soma producer)
- coherence PLV `∈ [0, 1]` (phase-locking value, nested per-pair dict)
- affect `valence ∈ [-1, 1]`, `arousal ∈ [0, 1]`, `dominance ∈ [-1, 1]` (thymos)
- `confidence ∈ [0, 1]` (nous; `1 - normalised_entropy`, clamped)
- drive `value ∈ [0, 1]` (thymos drives)
- `familiarity_scalar ∈ [0, 1]` (empatheia)
- `wellness ∈ [0, 1]`, `fatigue_value ∈ [0, 1]`
- `error_magnitude ≥ 0`, `phantasia.world_error.error ≥ 0` (non-negative, no
  declared ceiling)

Omitted as undefined (no hard bound declared): `expected_free_energy` (a signed
scalar with no documented range), latency/elapsed/duration fields and counts
beyond the generic non-negative case.

## Impact

- Affected: new `kaine/experiment/log_schema.py`.
- Boundary-preserving and read-only; no behaviour change to any running module.
- Ships safe: the sweep is an offline operator/analysis tool, never invoked from
  the cognitive cycle.
