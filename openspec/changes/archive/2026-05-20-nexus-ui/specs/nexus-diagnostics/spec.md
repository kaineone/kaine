## ADDED Requirements

### Requirement: Diagnostics route exposes metrics only
The Nexus diagnostics route SHALL display only numeric and
categorical metrics: module list, processing/experiential rates,
cycle slip distribution, soma wellness score, event-rate counters
per stream, fork count and ids, adapter list with hashes. The
route SHALL NEVER render message text, belief bodies, memory text,
internal speech, or Thymos affect reasons.

#### Scenario: Diagnostics page contains no message text
- **WHEN** Lingua has emitted external speech "secret message"
- **THEN** the diagnostics HTML response MUST NOT contain the text
  "secret message"

#### Scenario: Diagnostics SSE strips content payloads
- **WHEN** an event flows through the diagnostics SSE bridge whose
  payload contains a `text` field
- **THEN** the emitted SSE event's payload does NOT contain that
  `text` field

### Requirement: Diagnostics page exposes fork/merge controls
The diagnostics route SHALL list every snapshot stored under
ForkManager's snapshots_path with id, label, parent_id, and
timestamp. A POST handler SHALL invoke `ForkManager.fork(parent_id,
label, shed)` and another SHALL invoke `ForkManager.merge`.
Operations SHALL be audit-logged.

#### Scenario: Fork creates a new snapshot
- **WHEN** an operator POSTs `/diagnostics/forks` with
  `parent_id=<existing>` and `label=test`
- **THEN** a new snapshot file appears under the configured
  snapshots_path with parent_id matching the request
