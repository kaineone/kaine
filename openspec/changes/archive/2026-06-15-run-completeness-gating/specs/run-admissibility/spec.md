# run-admissibility (delta)

## ADDED Requirements

### Requirement: Finished runs are scannable for completeness
A finished run SHALL be scannable for completeness from its durable records and
SHALL be reported inadmissible, with reasons, when any of the following is
violated: the `cycle.tick` `tick_index` sequence is contiguous, every sink's
per-record `seq` sequence is contiguous, all expected streams produced at least
one record, and no record line failed to decrypt/parse. The system SHALL provide
`scan_run(run_id, *, root, expected_streams)` returning an `AdmissibilityReport`
(`admissible`, `tick_gaps`, `seq_gaps`, `missing_streams`, `parse_errors`) whose
`admissible` is true only when all four hold, and a CLI
`python -m kaine.experiment.admissibility <run_id>` that prints the report and
exits non-zero when the run is inadmissible. The expected-stream set SHALL be
supplied as data by the caller so the scanner does not import the evaluation
package. A malformed record line SHALL be counted as a parse error and SHALL NOT
raise.

#### Scenario: Complete run is admissible
- **WHEN** a run's records have a contiguous `cycle.tick` `tick_index` sequence, contiguous per-sink `seq` on every stream, all expected streams present, and no malformed lines
- **THEN** `scan_run` reports `admissible = true` with empty `tick_gaps`, `seq_gaps`, and `missing_streams` and `parse_errors = 0`

#### Scenario: A tick gap makes the run inadmissible
- **WHEN** the `cycle.tick` `tick_index` sequence skips a value (e.g. 0, 1, 3, 4)
- **THEN** `scan_run` reports `admissible = false` and lists the missing index in `tick_gaps`

#### Scenario: A seq gap makes the run inadmissible
- **WHEN** a sink's `seq` sequence skips a value (a silently dropped record)
- **THEN** `scan_run` reports `admissible = false` and lists the missing `seq` under that stream in `seq_gaps`

#### Scenario: A missing expected stream makes the run inadmissible
- **WHEN** an expected stream produced zero records this run
- **THEN** `scan_run` reports `admissible = false` and names the stream in `missing_streams`

#### Scenario: The bundle manifest carries the verdict
- **WHEN** a research bundle is built with a run id and an expected-stream list
- **THEN** the bundle manifest contains an `admissibility` block with the verdict and reasons, so an inadmissible run cannot reach analysis looking clean
