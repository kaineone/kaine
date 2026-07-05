# nexus-observability (delta)

## ADDED Requirements

### Requirement: Run identity surfaced on diagnostics
The Nexus dashboard SHALL surface the live run's identity — `run_id`, `seed`,
`git_sha`, `kaine_version`, and the `deterministic` flag — read from the active
`RunContext` and persisted by the cycle into `state/cycle/runtime.json`. The
diagnostics page SHALL render a "run identity" block from these fields, and
`metrics_snapshot` SHALL include them. All of these fields are non-content
run metadata; the surface SHALL carry no entity-interior content.

#### Scenario: Run identity renders when a run is live
- **WHEN** the cycle has minted a `RunContext` and written runtime.json
- **THEN** the diagnostics "run identity" block shows the run id, seed, git sha, and version
- **AND** `metrics_snapshot` includes `run_id`, `seed`, `git_sha`, `kaine_version`, and `deterministic`

#### Scenario: Run identity absent before a run starts
- **WHEN** no run context has been set (no runtime.json or no identity fields)
- **THEN** the run-identity block degrades gracefully and the page still loads

### Requirement: Supervision mode and safety-net gate badge
The Nexus dashboard SHALL surface the active supervision mode — `operator` or
`research` — and, in research mode, the four-condition safety-net gate `checks`
dict (`preservation_enabled`, `welfare_response_wired`, `logging_active`,
`self_check_passed` / `dry_self_check_passed`). The cycle SHALL write
`supervision_mode` (and, in research mode, the gate checks) into runtime.json.
The diagnostics page SHALL render a badge at the top, visually distinct from the
research-participation telemetry panel, and a research-mode badge SHALL be
visually prominent. These are non-content operational flags.

#### Scenario: Research-mode badge is prominent and shows gate checks
- **WHEN** the cycle booted in research mode with the safety-net gate satisfied
- **THEN** the diagnostics page shows a prominent research-mode badge with the gate checks

#### Scenario: Operator-mode badge is shown
- **WHEN** the cycle booted operator-present
- **THEN** the diagnostics page shows an operator-supervised badge and no gate-checks list

### Requirement: Preservation and welfare-protective events surfaced
The Nexus dashboard SHALL surface preservation and welfare-protective events —
`preservation.preserved`, `preservation.failed`, `preservation.skipped`, and
`welfare.protective_action` (source `preservation`, stream `preservation.out`) —
in a persistent panel analogous to the Spot console. The panel SHALL display
only an allowlist of non-content fields (e.g. `preservation_id`, `snapshot_id`,
`reason`, `action`/`action_taken`, `transition`, `monitor`), render a
`preservation.failed` event in the down/critical colour, and persist the last N
events in `sessionStorage` so a reload does not lose context. A
`HealthProber._preservation_block()` SHALL backfill the panel by reading the
incident-log directory (`state/cycle/preservation/`). No entity-interior content
SHALL be surfaced.

#### Scenario: A preservation event is shown and persisted
- **WHEN** a `preservation.preserved` event arrives on the diagnostics SSE stream
- **THEN** a line appears in the preservation panel with the preservation id, snapshot id, and reason
- **AND** the line is persisted so it survives a page reload

#### Scenario: A failed preservation is visually distinct
- **WHEN** a `preservation.failed` event arrives
- **THEN** its line renders in the down/critical colour

#### Scenario: Backfill reads the incident log without content
- **WHEN** the diagnostics page loads and the incident-log directory holds prior records
- **THEN** `_preservation_block()` returns the recent records using only allowlisted non-content fields

### Requirement: Live welfare status on the entity-care panel
The Nexus dashboard SHALL surface a compact numeric welfare-counter row —
unmaintained-fatigue crossings, sustained-VAD episodes, replay overload, and
sustained interoceptive distress — on the diagnostics entity-care panel, sourced
from the same aggregation as the evaluation tab. The row SHALL be numeric only
and carry no entity-interior content.

#### Scenario: Welfare counters render on the entity-care panel
- **WHEN** welfare counters are available (live registry or JSONL rollup)
- **THEN** the entity-care panel shows the four numeric counters

#### Scenario: Welfare counters absent degrade gracefully
- **WHEN** no welfare data is available
- **THEN** the row renders an empty/none state and the page still loads

### Requirement: Live admissibility indicator
The Nexus dashboard SHALL surface a lightweight live admissibility indicator that,
without scanning all run history, reports whether the current run's manifest is
present (`data/evaluation/runs/<run_id>/manifest.json`), the last tick index from
runtime.json, and a recording / gap-detected / unknown pill. A `HealthProber`
probe SHALL produce this block. The full completeness scan SHALL remain a
command-line operation.

#### Scenario: Recording when the manifest is present and ticks advance
- **WHEN** the current run's manifest exists and runtime.json reports a tick index
- **THEN** the admissibility indicator shows the manifest present, the last tick index, and a "recording" pill

#### Scenario: Unknown when no run is identifiable
- **WHEN** no run id is available from runtime.json
- **THEN** the admissibility indicator shows an "unknown" pill without error

### Requirement: Deterministic-mode indicator
The Nexus dashboard SHALL render a deterministic-mode indicator near the
cycle-rate charts, shown ONLY when the run's `deterministic` flag (from
runtime.json) is true, stating that timestamps are logical rather than wall-clock.
The indicator SHALL use the degraded colour and SHALL NOT appear in production
(non-deterministic) runs.

#### Scenario: Indicator shown in deterministic mode
- **WHEN** runtime.json reports `deterministic` true
- **THEN** a deterministic-mode badge appears near the cycle-rate charts

#### Scenario: Indicator hidden otherwise
- **WHEN** `deterministic` is false or absent
- **THEN** no deterministic-mode badge is shown
