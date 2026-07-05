# nexus-observability Specification

## Purpose
TBD - created by archiving change nexus-v4-observability. Update Purpose after archive.
## Requirements
### Requirement: Live streams for all active modules
The Nexus diagnostics SSE bridge SHALL relay the output streams of every active
module, including `empatheia.out`, `phantasia.out`, and the `workspace.broadcast`
stream (which carries `metadata['coherence']`), so no enabled module is invisible
in the live event feed.

#### Scenario: New module streams reach the feed
- **WHEN** Empatheia or Phantasia publishes an event while enabled
- **THEN** that event appears in the Nexus diagnostics SSE feed

#### Scenario: Disabled-module stream is a no-op
- **WHEN** a module is disabled and produces no events
- **THEN** its stream contributes nothing and the dashboard renders without error

### Requirement: Coherence (PLV) chart
Nexus SHALL render a phase-locking-value (coherence) time series from
`WorkspaceSnapshot.metadata['coherence']`. When the oscillatory layer is disabled
and the key is absent, the chart SHALL render empty without error rather than
breaking the page.

#### Scenario: Coherence updates when present
- **WHEN** a `workspace.broadcast` carries `metadata['coherence']`
- **THEN** the coherence chart's series advances with that value

#### Scenario: Coherence absent degrades gracefully
- **WHEN** the oscillator is disabled and no coherence key is present
- **THEN** the coherence chart shows an empty series and the page still loads

### Requirement: Fatigue-accumulator trend
Nexus SHALL render a Soma fatigue-accumulator trend from `soma.report`
`fatigue_value`, with the maintenance threshold shown as a reference, so the
operator can see how close the substrate is to triggering Hypnos maintenance.

#### Scenario: Fatigue trend advances
- **WHEN** `soma.report` events carrying `fatigue_value` are observed
- **THEN** the fatigue trend series advances and the threshold reference is shown

### Requirement: Welfare and prediction-error counts on the evaluation tab
Nexus SHALL surface, on the evaluation tab, the `welfare_observer` Gray-Zone
counts (unmaintained fatigue, sustained extreme VAD, replay overload), the
`prediction_error_observer` sliding-window statistics per source, and a coherence
summary — read from the live sidecar registry when available and otherwise from
the observer JSONL rollups. Each section SHALL render a "no data" state, never an
error, when its source is absent.

#### Scenario: Welfare counts are visible
- **WHEN** the welfare observer has recorded one or more Gray-Zone events
- **THEN** the evaluation tab shows the per-type counts

#### Scenario: Prediction-error stats are visible
- **WHEN** the prediction-error observer has accumulated samples
- **THEN** the evaluation tab shows per-source mean/p95/p99

#### Scenario: No observer data degrades gracefully
- **WHEN** neither a live registry nor observer JSONL is available
- **THEN** the welfare, prediction-error, and coherence sections render "no data"
  without error

### Requirement: State-encryption status probe
The Nexus health board SHALL report the `[security.state_encryption]` posture —
encrypted-at-rest, plaintext (disabled), or enabled-but-no-key (fail-closed) —
without ever reading or logging the encryption key.

#### Scenario: Encryption enabled with a key
- **WHEN** state encryption is enabled and a key is resolvable
- **THEN** the health board reports an encrypted-at-rest status and never logs the key

#### Scenario: Encryption enabled without a key
- **WHEN** state encryption is enabled but no key is resolvable
- **THEN** the health board reports a fail-closed (no-key) status

### Requirement: Fork merge-warning surfaced
The Nexus forks panel SHALL surface the `nous.merge_warning` flag when a fork
merge recorded a Nous policy divergence, so the operator is alerted to a posterior
clash across branches.

#### Scenario: Merge warning is shown
- **WHEN** a merge snapshot carries `nous.merge_warning`
- **THEN** the forks panel shows a warning marker for that fork

#### Scenario: No warning when absent
- **WHEN** a merge snapshot has no merge-warning flag
- **THEN** no warning marker is shown for that fork

### Requirement: Supervisor incident status on the health surface
The Nexus health snapshot SHALL include a `spot` block reporting the supervisor
incident state — `ok`, `recovery`, or `critical` — derived from the freeze control
(`frozen` and `source == "spot"` ⇒ `recovery`) and the escalation record
(`escalated` ⇒ `critical`), together with the affected `module`, `attempts`,
`max_attempts`, an operator `message`, and the saved `snapshot_id` when present.
The block SHALL contain only operational data (no sensory content) and SHALL be
served on `/diagnostics/health.json` so a freshly loaded or reconnected page paints
the correct state.

#### Scenario: Recovery state surfaced
- **WHEN** the freeze control is frozen with `source == "spot"` and no escalation
  is recorded
- **THEN** the health snapshot's `spot.state` is `"recovery"`

#### Scenario: Critical state surfaced
- **WHEN** an escalation record exists
- **THEN** the health snapshot's `spot.state` is `"critical"` and carries the
  operator message and `snapshot_id`

#### Scenario: Default ok state
- **WHEN** there is no Spot freeze and no escalation
- **THEN** the health snapshot's `spot.state` is `"ok"`

### Requirement: Operator alert UI for supervisor incidents
The diagnostics UI SHALL render a full-window alert border that turns yellow during
a `recovery` state and red during a `critical` state, a status banner carrying the
human message, and a live incident console fed by the `spot.out` bus stream
(`spot.status` flips the border/banner; `spot.log` lines append to the console).
`spot.out` SHALL be included in the diagnostics SSE streams. Any pulse animation on
the alert border SHALL be disabled under `prefers-reduced-motion`.

#### Scenario: Border reflects incident state
- **WHEN** the health snapshot reports `spot.state == "critical"`
- **THEN** the page renders the alert border in its red (critical) state

#### Scenario: Live console receives incident lines
- **WHEN** Spot publishes `spot.log` events during an incident
- **THEN** the diagnostics page appends those lines to the incident console via the
  SSE stream

#### Scenario: Reduced motion disables the pulse
- **WHEN** the operator's environment requests reduced motion
- **THEN** the alert border is shown without a pulsing animation

### Requirement: Entity-care status on the health surface
The Nexus health snapshot SHALL include a read-only `entity_care` block reporting the entity's
divergence/individuation summary and the CAL care-obligation checklist that applies before
decommission. The block SHALL be non-content (statuses and static obligation text only) and SHALL
NOT expose any destructive control — decommission remains a gated CLI action. The block SHALL be
guarded so a missing or unreadable signal yields a safe default rather than an error.

#### Scenario: Care block present and read-only
- **WHEN** the diagnostics health snapshot is produced
- **THEN** it includes an `entity_care` block with the divergence summary and the care-obligation
  checklist, and the diagnostics page exposes no delete/decommission control

#### Scenario: Safe default when signals are absent
- **WHEN** no divergence signals are available
- **THEN** the `entity_care` block renders a safe default summary without raising

### Requirement: GPU pre-flight status is surfaced read-only

The Nexus health snapshot SHALL include a read-only `gpu_preflight` block derived
from the last pre-flight verdict, reporting only non-content operational data:
per-device VRAM, evicted/loaded model ids, GPU process names, the KAINE services
detected, and an operator state. The block SHALL never raise; a missing or corrupt
pre-flight record SHALL yield state `unknown`. Nexus SHALL NOT expose any control
that terminates a process from this block.

#### Scenario: Blocked pre-flight surfaces as critical

- **WHEN** the last pre-flight recorded a `blocked` verdict
- **THEN** the `gpu_preflight` block reports state `critical` with the per-device
  shortfall

#### Scenario: No pre-flight record is unknown, not an error

- **WHEN** no pre-flight record exists
- **THEN** the `gpu_preflight` block reports state `unknown`
- **AND** the snapshot is produced without error

### Requirement: Nous health probe verifies the generative model builds

The Nous health probe SHALL confirm that the active-inference generative
model can be constructed, not merely that `pymdp` and `jax` are importable.
A broken dependency (e.g. numpy ABI mismatch) that only surfaces at
construction time would pass an import-only probe and give a false UP result.

The probe SHALL attempt `build_generative_model()` with default parameters
after confirming imports succeed.  The build attempt SHALL be guarded so
that any exception is caught within the probe and never propagates to the
caller.

#### Scenario: Imports and build succeed

- **WHEN** `pymdp` and `jax` are importable
- **AND** `build_generative_model()` completes without raising
- **THEN** the probe SHALL return `UP`
- **AND** the detail message SHALL include `"generative model built"`

#### Scenario: Imports succeed but build fails

- **WHEN** `pymdp` and `jax` are importable
- **AND** `build_generative_model()` raises any exception
- **THEN** the probe SHALL return `DEGRADED`
- **AND** the detail message SHALL include `"build failed"` and the exception message

#### Scenario: Import fails

- **WHEN** `pymdp` or `jax` cannot be imported
- **THEN** the probe SHALL return `DOWN` (unchanged from prior behaviour)

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

