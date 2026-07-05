## Why

When the Spot watchdog recovers a module crash — or exhausts its restart budget and
escalates — every detail of what happened is lost on the next clean boot.

The crash exception read at `spot.py:144` via `t.exception()` is **discarded**
immediately after the liveness check; neither the fault class nor the exception
repr survives. Snapshot success is never logged: a module that serialized cleanly
and one that hit `_serialize_error` look identical in the operational record.
The `spot.status` / `spot.log` bus events that Nexus shows live are **ephemeral**
(Redis Streams, MAXLEN ~100k, trimmed on every publish). And the two durable
files that do persist — `state/cycle/escalation.json` (single latest escalation)
and `state/cycle/control.json` (freeze state) — are **wiped on every clean boot**
by the `clear_escalation()` call in `__main__.py`.

The result: a follow-up research paper has no access to crash/recovery evidence
after restart. An operator debugging a recurring fault cannot see whether the same
module crashed the same way yesterday. A Guardian reviewing welfare-relevant events
cannot distinguish "Spot recovered in one attempt" from "Spot tried five times
before escalating."

This change adds a durable, append-only, structured **incident log** that captures
one JSONL record per lifecycle transition (detect → freeze → snapshot → restart →
escalate). All records for a single incident share a generated `incident_id`.
The log survives reboots, is never cleared at boot, respects the existing
state-encryption posture, and adds no module enables.

## What Changes

- A new `[spot.incident_log]` config block. Ships `enabled = true` so that any
  operator who enables Spot automatically gets the log; the shipped TOML keeps
  `[spot].enabled = false`, so the entire feature is dormant in a first-boot
  all-off config.
- Five JSONL transition records (detect, freeze, snapshot, restart, escalate),
  each written by Spot at the moment the transition occurs, all carrying a shared
  `incident_id` (UUID) and an ISO-8601 UTC `ts`.
- The currently-discarded exception repr (`t.exception()` at `spot.py:144`) is
  captured and written in the `detect` record instead of being dropped.
- `BaseModule.health()` metrics (`heartbeat_age_s`, `tasks_failed`, `tasks_total`)
  are consumed by Spot at detect time, which they currently are not.
- Snapshot success/failure per module (currently only failures reach `log.warning`;
  the full outcome map is buried inside the snapshot JSON) is recorded in the
  `snapshot` transition record: `modules_serialized_ok` count,
  `modules_serialize_errored` list, byte size, duration, encrypted flag.
- The existing ephemeral `spot.status` / `spot.log` bus events are **unchanged**
  for the Nexus live console.
- Storage: `AsyncJsonlSink` (`kaine/evaluation/sink.py`) reused for async,
  non-blocking, encrypted JSONL writes, extended with a **no-purge option**
  (`retention_days=0`) so research history is never auto-deleted.
- Privacy: `exception_repr` in the detect record is scrubbed of operator
  filesystem paths before write, replacing them with a `<PATH>` sentinel, per the
  project's no-personal-details rule.

## Impact

- **Config:** `config/kaine.toml` — new `[spot.incident_log]` block (`enabled`,
  `path`). The block ships alongside the existing `[spot]` section.
- **Code:** `kaine/cycle/spot.py` — capture exception at `assess()`, read
  `health()`, assign `incident_id` per incident in `_Incident`, emit five new
  `_write_incident_record()` calls; `SpotConfig.from_section` parses the new
  sub-block. `kaine/evaluation/sink.py` — add `retention_days=0` guard so
  `_enforce_retention` is a no-op when retention is disabled.
- **Tests:** incident records written for all five transitions; no-purge guard on
  `AsyncJsonlSink`; path-redaction of exception repr.
- **Safety:** ships disabled (Spot stays off). No module enables. No sensory
  content in any record. Exception reprs are path-scrubbed before write.
- **Welfare / ethics:** no entity boots required for this change (Spot is disabled
  in the shipped config). Implementation is a pure extension: the existing
  freeze/snapshot/restart/escalate logic is unchanged; only side-channel writes
  are added.
