# spot-supervisor Specification

## Purpose
TBD - created by archiving change add-spot-watchdog. Update Purpose after archive.
## Requirements
### Requirement: Always-on module supervisor
The cycle entrypoint SHALL run a supervisor component (Spot) as a task alongside
`cycle.run_forever`, when `[spot].enabled` is true. Spot SHALL NOT be a registered
module (it must act when modules fail and cannot watch itself). On each poll
(default `poll_interval_s = 2.0`) Spot SHALL assess every registered module's
liveness and drive recovery for at most one incident at a time. Spot SHALL ship
disabled by default.

#### Scenario: Disabled by default
- **WHEN** `config/kaine.toml` is loaded as shipped
- **THEN** `[spot].enabled` is `false` and no supervisor task runs

#### Scenario: Supervisor runs when enabled
- **WHEN** the cycle entrypoint boots with `[spot].enabled = true`
- **THEN** a Spot task is created next to the cycle and freeze-watch tasks and is
  awaited during shutdown

### Requirement: Module liveness detection
Spot SHALL classify each module as `alive`, `dead`, or `hung`. A module SHALL be
`dead` when any of its tasks finished with an exception, or returned while the
module was not stopping (an organ loop that exited on its own). A module SHALL be
`hung` only when its heartbeat age exceeds the configured timeout AND at least one
task is still running AND the entity is not in maintenance sleep. A module that is
merely quiet (no recent output but tasks running and heartbeat fresh) SHALL be
`alive`. When the registry's `hypnos` reports `is_sleeping`, hang flags SHALL be
suppressed (the crash signal still applies).

#### Scenario: Crashed task is dead
- **WHEN** a module's task has finished with an exception
- **THEN** Spot classifies that module as `dead`

#### Scenario: Quiet but live module is alive
- **WHEN** a module has published nothing recently but its tasks are running and
  its heartbeat is fresh
- **THEN** Spot classifies it as `alive` and takes no recovery action

#### Scenario: Sleep suppresses hang flags
- **WHEN** `hypnos.is_sleeping` is true and a module's heartbeat is stale
- **THEN** Spot does not classify that module as `hung`

### Requirement: Freeze the entity during recovery
On detecting a failed module Spot SHALL freeze the entity by writing the
operator-freeze control with `source = "spot"`, so the existing freeze-watch loop
pauses the cycle and halts perception. Spot SHALL resume (clear the freeze) only
when the control's `source` is `"spot"`, and SHALL never clear an operator freeze.
When the control is already frozen with `source = "operator"`, Spot SHALL take no
recovery action.

#### Scenario: Spot freeze halts the entity
- **WHEN** Spot detects a `dead` module
- **THEN** it writes the freeze control with `source = "spot"` before attempting
  restart

#### Scenario: Spot does not clear an operator freeze
- **WHEN** the freeze control is frozen with `source = "operator"`
- **THEN** Spot performs no recovery and does not modify the control

### Requirement: Snapshot before restart and at escalation
Spot SHALL take a last-good `ForkManager` snapshot before the first restart attempt
of an incident, and a final snapshot at escalation. Snapshots SHALL contain only
each module's `serialize()` output (numeric/derived state); no raw sensory data.

#### Scenario: Pre-restart snapshot
- **WHEN** Spot begins recovery for a module (attempt count 0)
- **THEN** it records a snapshot labeled for that module before the first restart

#### Scenario: Escalation snapshot
- **WHEN** Spot reaches the maximum restart attempts
- **THEN** it records a final snapshot before shutting modules down

### Requirement: Restart ladder
Spot SHALL attempt a light restart (recreate the module's own tasks via
`BaseModule.restart`) for modules that hold no external resources, and a heavy
rebuild (reconstruct via the boot factory, swap via `ModuleRegistry.replace`,
re-run post-build wiring, then `ForkManager.restore` the last-good state) for
modules whose `holds_external_resources()` is true. A heavy rebuild SHALL shut the
old instance down before constructing the new one, and SHALL re-fetch any sibling
references (e.g. Hypnos's mnemos/thymos/phantasia) from the registry.

#### Scenario: Light restart for a pure module
- **WHEN** Spot restarts a module whose `holds_external_resources()` is false
- **THEN** it calls the module's `restart()` and re-assesses liveness

#### Scenario: Heavy rebuild for a resource-holding module
- **WHEN** Spot restarts a module whose `holds_external_resources()` is true
- **THEN** it shuts the old instance down, builds a fresh instance via the boot
  factory, swaps it in via `ModuleRegistry.replace`, re-runs post-build wiring, and
  restores the last-good snapshot into it

### Requirement: Escalation after repeated failures
Spot SHALL escalate after `max_restart_attempts` (default 5) failed restarts of the
same module in one incident. Escalation SHALL take a final snapshot, shut down all
modules cleanly, write `state/cycle/escalation.json` with operational fields only
(`escalated`, `module`, `attempts`, `snapshot_id`, `escalated_at`, operator
`message`), and cause the cycle process to exit non-zero so it does not auto-retry.
Spot SHALL NOT reboot the machine; the escalation message SHALL instruct the
operator to reboot and restart. A clean boot SHALL clear any prior escalation
record.

#### Scenario: Five failures escalate
- **WHEN** a module fails restart five times in one incident
- **THEN** Spot writes `escalation.json`, shuts down all modules, and signals a
  non-zero process exit

#### Scenario: Escalation does not auto-retry
- **WHEN** Spot has escalated
- **THEN** the process exits and does not itself restart the modules or the machine

#### Scenario: Clean boot clears escalation
- **WHEN** the cycle entrypoint starts cleanly
- **THEN** any existing `escalation.json` is cleared

### Requirement: Incident events on the bus
Spot SHALL publish incident events to a `spot.out` stream: `spot.status` events
carrying the current state (`ok` | `recovery` | `critical`) with the affected
module, attempt count, and a human message; and `spot.log` events carrying a
level and a human-readable line as the incident progresses. These events SHALL
contain only operational data (no sensory content) so the Nexus diagnostics stream
can fan them out.

#### Scenario: Recovery publishes status and log
- **WHEN** Spot begins recovering a module
- **THEN** it publishes a `spot.status` event with state `recovery` and one or more
  `spot.log` events describing the attempt

### Requirement: Durable incident logging

Spot SHALL write a durable, append-only, structured incident log capturing one
JSONL record per lifecycle transition (detect, freeze, snapshot, restart, escalate).
All records belonging to one incident SHALL share a generated `incident_id` (UUID4).
Every record SHALL carry `ts` (ISO-8601 UTC), `incident_id`, `module`, and
`transition`. The incident log SHALL be stored under `state/cycle/incidents/` in
daily-rotated JSONL files.

The incident log SHALL survive process restarts and reboots. It SHALL **never** be
cleared at boot — explicitly contrasting with `state/cycle/escalation.json` and
`state/cycle/control.json`, which are wiped on every clean boot for operational
reasons. The `clear_escalation()` call in the cycle entrypoint SHALL NOT touch the
incident log.

The incident log is governed by a `[spot.incident_log]` config block. It SHALL
ship with `enabled = true` so any operator who enables Spot automatically receives
the log. Because `[spot].enabled` ships `false`, the entire feature is dormant in
the shipped all-off configuration; no module enables are added or changed.

#### Scenario: Log survives reboot

- **WHEN** Spot records incident transitions across multiple runs
- **THEN** previous runs' JSONL files remain in `state/cycle/incidents/`
  after a clean boot
- **AND** `clear_escalation()` at boot does not delete or truncate incident files

#### Scenario: Disabled Spot produces no log

- **WHEN** `[spot].enabled = false` (the shipped default)
- **THEN** no `AsyncJsonlSink` is constructed for the incident log
- **AND** no files are written under `state/cycle/incidents/`

#### Scenario: Enabled Spot with disabled incident log

- **WHEN** `[spot].enabled = true` AND `[spot.incident_log].enabled = false`
- **THEN** no incident records are written
- **AND** the existing ephemeral bus events (`spot.status`, `spot.log`) continue
  to be published unchanged

---

### Requirement: Crash cause capture

At fault detection, Spot SHALL capture the exception from `t.exception()` and
include its repr in the `detect` transition record rather than discarding it. The
captured repr SHALL be scrubbed of operator filesystem paths before write, replacing
matching tokens with the sentinel `<PATH>`. For hung modules (no completed task
exception), `exception_repr` SHALL be `null`.

Spot SHALL also read `BaseModule.health()` at detection time and include
`heartbeat_age_s`, `tasks_failed`, and `tasks_total` in the detect record. A
monotonic `poll_index` counter SHALL be included to identify which poll cycle the
detection occurred in.

The existing ephemeral `spot.status` and `spot.log` bus events SHALL remain
unchanged; the detect record is a durable side-channel, not a replacement.

#### Scenario: Dead module — exception captured

- **WHEN** Spot detects a module as `dead` because a task finished with an exception
- **THEN** the `detect` transition record carries `fault_class = "dead"` and a
  non-null `exception_repr` containing the scrubbed repr of that exception

#### Scenario: Dead module — path scrubbed

- **WHEN** the exception repr contains an operator filesystem path
  (e.g. `/home/operator/...`)
- **THEN** the `detect` transition record carries `<PATH>` in place of the path
  token
- **AND** the raw path is never written to the incident log

#### Scenario: Hung module — no exception repr

- **WHEN** Spot detects a module as `hung` (stale heartbeat, task still running)
- **THEN** the `detect` transition record carries `fault_class = "hung"` and
  `exception_repr = null`

#### Scenario: Health metrics present

- **WHEN** Spot emits a `detect` record
- **THEN** the record carries `heartbeat_age_s`, `tasks_failed`, and `tasks_total`
  read from `BaseModule.health()` at the moment of detection

---

### Requirement: Snapshot outcome recording

Spot SHALL write a `snapshot` transition record after each `ForkManager.snapshot()`
call. The record SHALL include: `snapshot_id`, `byte_size` (total bytes of the
snapshot bundle), `modules_serialized_ok` (count of modules that serialized without
error), `modules_serialize_errored` (list of module names that raised in
`serialize()`), `encrypted` (whether `StateEncryptor` is enabled at write time),
`duration_ms` (wall-clock time for the snapshot), and `label` (the snapshot label
string, e.g. `"spot-pre-restart:<mod>"` or `"spot-escalation:<mod>"`).

This makes per-module snapshot success/failure visible at the record level, rather
than buried inside the snapshot bundle JSON.

#### Scenario: All modules serialized

- **WHEN** `ForkManager.snapshot()` succeeds with no per-module errors
- **THEN** the `snapshot` record carries `modules_serialize_errored = []` and
  `modules_serialized_ok` equals the total module count

#### Scenario: Partial serialization failure

- **WHEN** one or more modules raise during `serialize()`
- **THEN** the `snapshot` record carries those modules' names in
  `modules_serialize_errored` and `modules_serialized_ok` reflects the count
  that succeeded

#### Scenario: Snapshot failure

- **WHEN** `ForkManager.snapshot()` itself raises (the whole snapshot fails)
- **THEN** a `snapshot` record is still written with `snapshot_id = null` and a
  `modules_serialize_errored` list reflecting what was known before the failure

---

### Requirement: Restart transition recording

Spot SHALL write a `restart` transition record after each restart attempt,
capturing: `attempt` (1-based), `max_attempts`, `path` (`"light"` or `"heavy"`),
`outcome` (`"recovered"` or `"failed"`), `latency_ms`, `last_good_restored`
(whether `ForkManager.restore` was called), and `post_assess` (the liveness
assessment after restart).

#### Scenario: Successful light restart

- **WHEN** a light restart (`BaseModule.restart()`) succeeds and post-assess
  is `"alive"`
- **THEN** the `restart` record carries `path = "light"`, `outcome = "recovered"`,
  and `post_assess = "alive"`

#### Scenario: Failed heavy restart

- **WHEN** a heavy rebuild fails and post-assess is `"dead"` or `"hung"`
- **THEN** the `restart` record carries `path = "heavy"`, `outcome = "failed"`,
  and `post_assess` reflecting the re-assessment

---

### Requirement: Encryption and retention

The incident log SHALL be encrypted at rest when `[security.state_encryption]`
is enabled, using the same `StateEncryptor` path (`get_state_encryptor().encrypt_text`)
that `AsyncJsonlSink._encode_line` already calls. No additional encryption code
is required in Spot.

The incident log retention purge SHALL be unconditionally disabled (equivalent to
`retention_days=0` on `AsyncJsonlSink`). The 30-day default purge behaviour of
`AsyncJsonlSink` SHALL NOT apply to the incident log. The `[spot.incident_log]`
config block does not expose a `retention_days` key; operators cannot configure
auto-deletion.

#### Scenario: Encrypted deployment

- **WHEN** `[security.state_encryption].enabled = true`
- **THEN** each line in `state/cycle/incidents/*.jsonl` is AES-256-GCM encrypted
  using the process-global `StateEncryptor`
- **AND** the `snapshot` transition record carries `encrypted = true`

#### Scenario: Plaintext deployment

- **WHEN** `[security.state_encryption].enabled = false` (the shipped default)
- **THEN** incident log lines are written as plaintext JSONL
- **AND** the `snapshot` transition record carries `encrypted = false`

#### Scenario: Retention purge disabled

- **WHEN** the incident log sink performs its daily-rotation maintenance
- **THEN** no incident log files are deleted regardless of their age
- **AND** all historical incident records remain on disk

### Requirement: Structured incident bus event per lifecycle transition

Spot SHALL publish a structured `spot.incident` bus event at each lifecycle
transition (detect, freeze, snapshot, restart, escalate), IN ADDITION to — and
never in place of — the existing ephemeral `spot.status` / `spot.log` events and
the durable `state/cycle/incidents/` log. The event SHALL be published via Spot's
existing bus publish path with `source = "spot"` and `type = "spot.incident"`,
and SHALL carry the incident's `incident_id`, the `transition`, the affected
`module`, the fault metadata (`fault_class` for detect; `fault_type` for freeze),
the transition-specific operational fields already recorded in the durable
incident record (freeze reason; snapshot id/byte size; restart path / outcome /
latency / restored-checkpoint flag; escalate attempts / outcome / final snapshot
id), and a cycle position. The cycle position SHALL always include Spot's
`poll_index` and SHALL include the cycle's `tick_index` when a tick-index
provider is available to Spot (a best-effort callable wired at construction); a
`tick_index` SHALL NOT be fabricated when no provider is available. Any free-text
field SHALL be scrubbed of operator filesystem paths (the same scrubber used by
the durable incident log) before publish. The durable incident log and the
`spot.status` / `spot.log` events SHALL remain unchanged by this requirement.

#### Scenario: Incident event published at each transition

- **WHEN** a `dead` module is detected, frozen, snapshotted, and restarted in one
  poll
- **THEN** Spot publishes a `spot.incident` event with `source = "spot"` for the
  `detect`, `freeze`, `snapshot`, and `restart` transitions, each carrying the
  same `incident_id`, the `module`, and the transition-specific fields

#### Scenario: Ephemeral status/log events are still published

- **WHEN** Spot handles an incident
- **THEN** the existing `spot.status` and `spot.log` events are still published
  alongside the new `spot.incident` events (none is replaced)

#### Scenario: Cycle position is included

- **WHEN** Spot is constructed with a tick-index provider and publishes a
  `spot.incident` event
- **THEN** the event payload carries `poll_index` and a `tick_index` read from
  the provider
- **AND WHEN** no tick-index provider is available
- **THEN** the event payload carries `poll_index` and no fabricated `tick_index`

#### Scenario: Operator paths are scrubbed

- **WHEN** a detect event is published for a module whose crash exception repr
  contains an operator filesystem path
- **THEN** the published `spot.incident` payload contains `<PATH>` and never the
  raw path

### Requirement: Run-level freeze annotation in the research event log

The research event log SHALL capture `spot.incident` bus events (and the
`spot.incident.*` subtype family) into privacy-filtered records under the
export-eligible `data/evaluation/research_events/` directory, so that a run whose
data was collected across a Spot freeze carries the annotation. Each captured
record SHALL carry the `incident_id` (joining it to the durable incident
provenance) and SHALL be stamped with the active run's `run_id` (joining it to
the run) when a run context is set. The record SHALL include only the allowlisted
operational fields of the incident event (transition, module, fault metadata,
snapshot id, restart outcome/path/latency, escalate outcome, cycle position) and
SHALL NOT include any content field.

#### Scenario: Incident recorded with incident_id and run_id

- **WHEN** the research observer reads a `spot.incident` event carrying an
  `incident_id` while a run context is set
- **THEN** it writes one research-event record carrying that `incident_id` and
  the run's `run_id`

#### Scenario: Incident recorded without a run context

- **WHEN** the research observer reads a `spot.incident` event and no run context
  is set
- **THEN** it still writes the record with the `incident_id`, and no `run_id` is
  added

#### Scenario: Operational fields kept, content dropped

- **WHEN** the research observer records a `spot.incident` event
- **THEN** the record carries the allowlisted operational fields and no content
  field (per the observer's allowlist-by-construction privacy filter)

