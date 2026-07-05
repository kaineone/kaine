## ADDED Requirements

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
