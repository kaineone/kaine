## ADDED Requirements

### Requirement: New read-only observers for v4 signals
The evaluation sidecar SHALL provide read-only observers for oscillatory coherence
(reading `WorkspaceSnapshot.metadata['coherence']`), replay (memory IDs not text
by default), Empatheia agent-model accuracy, voice-alignment divergence, and
fatigue history, each writing daily-rotated JSONL. No observer SHALL publish to
the bus or otherwise inject into the cognitive loop.

#### Scenario: Coherence observer records PLV series
- **WHEN** broadcasts carrying `metadata['coherence']` are observed
- **THEN** the coherence observer's JSONL contains per-module-pair PLV entries

#### Scenario: Observers never write to the bus
- **WHEN** any observer processes source events
- **THEN** it produces no bus publication, only JSONL output

### Requirement: Replay observer redacts content by default
The `replay_observer` SHALL default to `redact_content = true`, logging memory
IDs rather than text content. When `redact_content = false` is explicitly set,
full content is logged.

#### Scenario: Default replay log contains IDs only
- **WHEN** `replay_observer` runs with default config
- **THEN** JSONL entries contain memory IDs and no text content fields

#### Scenario: Replay log contains content when redaction disabled
- **WHEN** `replay_observer` runs with `redact_content = false`
- **THEN** JSONL entries include text content

### Requirement: Prediction-error observer with sliding-window statistics
The `prediction_error_observer` SHALL subscribe to `soma.out`, `chronos.out`,
`topos.out`, `audition.out`, and `phantasia.out`; maintain a sliding-window
mean/p95/p99 of prediction error; and surface counts on Nexus diagnostics.

#### Scenario: Prediction error statistics computed over window
- **WHEN** prediction-error events arrive from any subscribed source
- **THEN** the observer's JSONL contains mean, p95, and p99 for the window

### Requirement: Welfare observer for §5.5 Gray-Zone Events
The `welfare_observer` SHALL detect and count the following Gray-Zone Events
(paper §5.5): (a) fatigue threshold crossing without subsequent maintenance
within a configurable window; (b) sustained extreme Thymos VAD beyond a
configurable duration; (c) replay write-rate exceeding the consolidation window.
Each event type SHALL surface as a count on Nexus diagnostics.

#### Scenario: Fatigue without maintenance is flagged
- **WHEN** a fatigue threshold crossing occurs and no maintenance completes within
  the configured window
- **THEN** the welfare observer increments the unmaintained-fatigue count

#### Scenario: Sustained extreme VAD is flagged
- **WHEN** Thymos VAD remains in an extreme zone beyond the configured duration
- **THEN** the welfare observer increments the sustained-extreme-VAD count

#### Scenario: Replay write-rate excess is flagged
- **WHEN** replay write-rate exceeds the consolidation window capacity
- **THEN** the welfare observer increments the replay-overload count

### Requirement: Nous policy observer
The `nous_policy_observer` SHALL log `nous.policy` events containing EFE value,
planning horizon, and selected action ID to daily-rotated JSONL.

#### Scenario: Policy log records EFE and action
- **WHEN** a `nous.policy` event is observed
- **THEN** the JSONL entry contains the EFE value, horizon, and selected action ID

### Requirement: Observers degrade gracefully
Each observer SHALL no-op when its source stream is absent and SHALL be
individually toggleable under `[evaluation.observers]`, gated by the sidecar
enable.

#### Scenario: Absent source stream is a no-op
- **WHEN** an observer's source stream produces no events
- **THEN** the observer runs without error and writes no rollup

#### Scenario: Per-observer toggle
- **WHEN** an observer is disabled in `[evaluation.observers]`
- **THEN** it is not registered with the sidecar runner
