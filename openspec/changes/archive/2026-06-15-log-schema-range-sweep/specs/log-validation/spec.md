# log-validation (delta)

## ADDED Requirements

### Requirement: Logged records are re-validatable against physical ranges
Logged records SHALL be re-validatable post-run against a declared schema of
physically-possible numeric ranges, and any out-of-range value SHALL be reported
as a violation (fail-closed). The system SHALL provide `sweep_run(run_id, *,
root)` returning a list of violations, each naming the stream, field, value, and
the bound it broke, and a CLI `python -m kaine.experiment.log_schema <run_id>`
that prints the violations and exits non-zero when any exist. The schema SHALL
declare ranges taken from the producing modules (e.g. `salience ∈ [0, 1]`,
`prediction_error ≥ 0`, coherence PLV `∈ [0, 1]`, `valence ∈ [-1, 1]`,
`arousal ∈ [0, 1]`, `dominance ∈ [-1, 1]`, `confidence ∈ [0, 1]`, drive
`value ∈ [0, 1]`, `familiarity ∈ [0, 1]`) and SHALL use a generic `>= 0` where no
hard upper bound is defined and omit fields with no defined bound rather than
guessing. The sweep SHALL read records via the shared run-records loader
(decrypting both encrypted and plaintext lines) without importing the evaluation
package.

#### Scenario: In-range records have no violations
- **WHEN** a run's records hold only in-range values (e.g. `prediction_error = 0.0`, `valence = -0.5`, `confidence = 0.7`)
- **THEN** `sweep_run` returns an empty violation list and the CLI exits zero

#### Scenario: A negative prediction error is a violation
- **WHEN** a record carries `prediction_error = -0.3`
- **THEN** `sweep_run` reports a violation naming `prediction_error`, the value `-0.3`, and the bound `[0, ∞)`

#### Scenario: An out-of-bounds affect value is a violation
- **WHEN** a record carries `valence = 2.0` (outside `[-1, 1]`)
- **THEN** `sweep_run` reports a violation naming `valence`, the value `2.0`, and the bound `[-1, 1]`

#### Scenario: An out-of-bounds confidence is a violation
- **WHEN** a record carries `confidence = 1.5` (outside `[0, 1]`)
- **THEN** `sweep_run` reports a violation naming `confidence`, the value `1.5`, and the bound `[0, 1]`, and the CLI exits non-zero

#### Scenario: An out-of-range coherence value is a violation
- **WHEN** a coherence record carries a per-pair PLV greater than 1.0
- **THEN** `sweep_run` reports a violation naming that pair and the bound `[0, 1]`
