## MODIFIED Requirements

### Requirement: The export path enforces completeness and range admissibility

The research export path SHALL apply both admissibility checks — the completeness
gate (contiguous ticks and per-sink sequence numbers, all expected streams present,
no parse errors) and the log-range sweep (every logged number within its declared
range) — and SHALL block an inadmissible run from the default export. Both verdicts
SHALL be recorded in the bundle manifest.

`require_admissible` SHALL default to enabled. An operator MAY override to export an
inadmissible run, but the override SHALL be explicit and SHALL be recorded in the
manifest with a reason.

A run that experienced a process restart or otherwise spans multiple `run_id`s or a
reset per-sink sequence SHALL NOT be reported as clean; the admissibility report
SHALL flag it.

#### Scenario: Out-of-range run is blocked by default

- **WHEN** a run contains a logged value outside its declared range and no override
  is set
- **THEN** the default export blocks it as inadmissible

#### Scenario: Incomplete run is blocked by default

- **WHEN** a run is missing an expected stream or has a sequence gap and no override
  is set
- **THEN** the default export blocks it as inadmissible

#### Scenario: Restart is flagged, not clean

- **WHEN** admissibility is scanned over a run that reset its per-sink sequence
  mid-way
- **THEN** the report flags a restart/multi-process condition rather than reporting
  clean

#### Scenario: Explicit override is recorded

- **WHEN** an operator sets the explicit override to export an inadmissible run
- **THEN** the bundle exports
- **AND** the manifest records the override and its reason
