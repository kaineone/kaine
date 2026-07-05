## ADDED Requirements

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
