# Design — Spot incident log

## 1. Problem statement

Spot already executes a well-defined lifecycle: detect a crash or hang → freeze
the entity → snapshot state → attempt restart (up to N times) → escalate. Each
step produces observable side effects, but none are durably recorded in a form
that survives a reboot:

| Current artifact | Problem |
|---|---|
| `t.exception()` at `spot.py:144` | Read once, then discarded; fault class and cause are gone |
| `spot.status` / `spot.log` bus events | Redis Streams ring buffer (MAXLEN ~100k); Nexus shows them live, then they are trimmed and lost |
| `state/cycle/escalation.json` | Single latest escalation only; wiped on every clean boot via `clear_escalation()` in `__main__.py` |
| `state/cycle/control.json` | Single live freeze state; also reset at boot |
| Snapshot JSON (in `state/forks/`) | Success/failure detail per module is embedded inside the snapshot bundle; there is no index of "which modules serialized OK vs errored in snapshot X" accessible without unpacking the bundle |

A research paper or a Guardian welfare review needs structured, durable,
per-transition evidence: "at 14:32:07 UTC, module `lingua` was detected dead
(exception: ConnectionResetError), Spot froze the entity, snapshot
`snap-a1b2c3` captured 13 of 14 modules (1 errored), restart attempt 1 of 5
succeeded."

## 2. Record schema

One JSONL line per transition. All records carry:

```
ts              ISO-8601 UTC timestamp (str)
incident_id     UUID4 (str) — shared by all records for one incident
module          str — the module being recovered
transition      str — one of "detect" | "freeze" | "snapshot" | "restart" | "escalate"
```

Additional fields per transition:

### 2.1 `detect`

```
fault_class          "dead" | "hung"
exception_repr       str | null — repr(exc) from the discarded t.exception(), path-scrubbed
heartbeat_age_s      float — from BaseModule.health()["heartbeat_age_s"]
tasks_failed         int   — from BaseModule.health()["tasks_failed"]
tasks_total          int   — from BaseModule.health()["tasks_total"]
poll_index           int   — monotonic poll counter within this Spot instance run
```

`exception_repr` is `null` for hung modules (no completed task exception).
For dead modules it is `repr(t.exception())` read at the point where `spot.py`
currently calls `t.exception()` and then discards the result. The repr is
path-scrubbed before write (see §5).

`BaseModule.health()` already computes all metrics as a pure, never-raises dict
(`kaine/modules/base.py:56-83`). Spot currently calls `module.heartbeat_age()`
directly and never calls `health()`; the detect record is the first consumer.

### 2.2 `freeze`

```
reason       str — the reason string written to control.json
source       "spot"
fault_type   "dead" | "hung"  — structured mirror of the fault_class, not embedded in free text
```

`fault_type` is a structured extraction of what is currently embedded only in
the `reason` string (e.g. `"spot: lingua dead"`). Downstream analytics can
filter on `fault_type` without text parsing.

### 2.3 `snapshot`

```
snapshot_id              str | null
byte_size                int  — total bytes written to the snapshot bundle
modules_serialized_ok    int  — count of modules whose serialize() succeeded
modules_serialize_errored  list[str] — names of modules that raised in serialize()
encrypted                bool — whether StateEncryptor is enabled
duration_ms              float — wall-clock time for the snapshot call
label                    str  — "spot-pre-restart:<mod>" | "spot-escalation:<mod>"
```

These fields surface the per-module outcome currently buried in the snapshot
JSON. `ForkManager.snapshot()` returns a snapshot object; to populate
`modules_serialize_errored` the Spot wrapper either reads the snapshot metadata
dict (if ForkManager already records it) or wraps the serialize calls with
per-module guards and collects the errored names. The design prefers reading
from the returned snapshot object rather than reimplementing serialization logic.

`byte_size` is the file size of the completed snapshot bundle, measured after
`ForkManager.snapshot()` returns.

### 2.4 `restart`

```
attempt           int   — 1-based attempt number within this incident
max_attempts      int   — SpotConfig.max_restart_attempts
path              "light" | "heavy"
outcome           "recovered" | "failed"
latency_ms        float — wall-clock time for the restart call
last_good_restored  bool — whether ForkManager.restore was called
post_assess       "alive" | "dead" | "hung" — result of re-assess after restart
```

One restart record per attempt. `outcome = "recovered"` when the post-restart
assess returns `"alive"`.

### 2.5 `escalate`

```
attempts          int  — total attempts before escalation
final_snapshot_id str | null
outcome           "halted"
```

Emitted once, after `_escalate()` writes `escalation.json`. `outcome` is always
`"halted"` for the v1 escalation path (Spot halts and waits for operator
reboot); the field is included for future extensibility (e.g. a soft-escalation
path that pages the operator but keeps running).

## 3. Storage

### 3.1 Location

`state/cycle/incidents/` — a subdirectory of `state/cycle/`, the established
home for Spot-related operational state (`escalation.json`, `control.json`).

This is intentionally distinct from `data/evaluation/` (the evaluation sidecar
observer tree). The incident log is not an evaluation observer: it is a cycle
safety artifact that records facts about the cycle's own fault-recovery
machinery. Keeping it under `state/cycle/` makes it clear it is operational
state, not a user-configurable evaluation output. Operators who inspect
`state/cycle/` after an incident find everything in one place.

### 3.2 Persistence across reboots

`state/cycle/incidents/` is **never cleared at boot**. This is the load-bearing
contrast with `state/cycle/escalation.json` and `state/cycle/control.json`,
which both serve single-state operational needs and are reset at boot.
The incident log serves a historical research need: every crash/recovery event
from every run must accumulate. It is never touched by `clear_escalation()` or
any other boot-time reset in `__main__.py`.

### 3.3 File format and rotation

Daily-rotated JSONL files named `incidents-<UTC-date>.jsonl` under
`state/cycle/incidents/`. Rotation is handled by `AsyncJsonlSink`'s existing
`_target_path()` logic. Within a day, records are appended in transition order.
An incident that spans midnight (e.g. detect on day D, restart on D+1) produces
records in two files; the shared `incident_id` links them.

### 3.4 Retention

**Retention purge MUST be disabled for the incident log.** This is explicitly
different from the default `AsyncJsonlSink` behaviour (30-day purge) used by the
evaluation sidecar observers. Research history must not be auto-deleted.

Implementation: pass `retention_days=0` to `AsyncJsonlSink`. The
`_enforce_retention()` method already short-circuits when
`self._retention_days <= 0`, so this requires no new code path — only
documentation and configuration enforcement. The `[spot.incident_log]` config
block does not expose a `retention_days` key; retention purge is unconditionally
disabled for this sink.

### 3.5 Storage mechanism — recommendation

**Recommended: reuse `AsyncJsonlSink`** with `retention_days=0`.

> Boundary note (resolved during implementation): `AsyncJsonlSink` originally
> lived in `kaine/evaluation/sink.py`, but Spot is core cycle code and the
> sidecar boundary forbids core modules importing `kaine.evaluation` (only the
> cycle/nexus entrypoints may). The sink is a generic persistence primitive, so
> it was extracted to `kaine/persistence/jsonl_sink.py` (re-exported from
> `kaine/evaluation/sink.py` for the observers). The incident log imports it from
> `kaine.persistence`, respecting the boundary while still reusing the one writer.

Rationale:
- Async, non-blocking: writes go through an `asyncio.Queue`; the cycle and Spot
  are never blocked on disk I/O.
- Encryption: `_encode_line` already calls
  `get_state_encryptor().encrypt_text(line)`, so encryption at rest is automatic
  when `[security.state_encryption]` is enabled — no new encryption code needed.
- Daily rotation: already implemented.
- No-purge: `retention_days=0` triggers the existing short-circuit.
- Tests: `write_sync()` exists for synchronous test use.

Alternative considered: a small atomic-append writer mirroring the discipline of
`kaine/cycle/escalation_state.py` (atomic tmp→rename, `StateEncryptor` called
explicitly, no queue). This would be simpler in line count but would block the
async loop on disk I/O and require duplicating the encryption call already
implemented in `AsyncJsonlSink`. Not recommended.

## 4. Configuration

New `[spot.incident_log]` table in `config/kaine.toml`, placed directly under
the existing `[spot]` block:

```toml
[spot.incident_log]
enabled = true
path = "state/cycle/incidents"
```

`enabled = true` is the shipped default. The rationale: any operator who
deliberately enables Spot (by setting `[spot].enabled = true`) should get the
incident log automatically; it is the primary research-value output of Spot. An
operator who wants to disable it can set `[spot.incident_log].enabled = false`.

**First-boot / all-off posture:** the shipped `[spot].enabled = false` means
Spot never runs, so `[spot.incident_log]` is entirely dormant. The incident log
does not add a module enable, does not change any module toggle, and does not
affect the all-off guard in `tests/test_kaine_toml.py`. The `enabled = true`
default in `[spot.incident_log]` is irrelevant until an operator deliberately
sets `[spot].enabled = true`.

`SpotConfig.from_section` is extended to parse the `incident_log` sub-table and
reject unknown keys (consistent with its existing validation pattern).

## 5. Privacy and path scrubbing

Exception reprs (`repr(exc)`) may contain operator filesystem paths, e.g.
`FileNotFoundError: [Errno 2] No such file or directory: '/home/<user>/...'`.

Before writing `exception_repr` to the incident log, Spot applies a path-
scrubbing pass that replaces any absolute path token matching a common OS path
pattern (`/home/...`, `/root/...`, `/Users/...`, `C:\...`) with the sentinel
`<PATH>`. The scrub is best-effort (regex over the repr string) and logs a
debug-level note when a substitution occurs.

This is consistent with the project's no-personal-details rule (ref: memory
`feedback_no_personal_details_public.md`): operator filesystem paths must not
appear in the kaine repo, PRs, commit messages, or committed files.

The scrubbed `exception_repr` is what is written to disk. The original is never
logged or stored. Module names, fault metadata, snapshot IDs, sizes, timings,
and attempt counts are non-sensitive operational data and require no scrubbing.

## 6. Encryption at rest

When `[security.state_encryption].enabled = true`, every line in the incident
log is AES-256-GCM encrypted using the same `StateEncryptor` path
(`kaine/security/crypto.py` `get_state_encryptor().encrypt_text`) that
`AsyncJsonlSink._encode_line` already calls. No new encryption code is needed.
The `encrypted` field in the `snapshot` transition record reflects whether
`StateEncryptor.enabled` is true at the time of the snapshot.

## 7. Interaction with existing Spot logic

All changes to `spot.py` are **additive side-channel writes**. The existing
freeze/snapshot/restart/escalation logic is not modified:

- `control_state.freeze()` still runs and still sets `control.json`.
- `ForkManager.snapshot()` still runs and still writes the snapshot bundle.
- `BaseModule.restart()` / `_rebuild_module()` still run.
- `escalation_state.write_escalation()` still runs and still writes
  `escalation.json`.
- The `spot.status` / `spot.log` bus publish calls are unchanged.

New code adds:
1. `incident_id` field on `_Incident` (UUID generated on first detect).
2. `poll_index` counter on `Spot`.
3. `_write_incident_record(record: dict)` coroutine wrapping `sink.write()`.
4. Five call sites inserting `await self._write_incident_record(...)` at each
   transition point.
5. `_IncidentLogSink` lifecycle (start at Spot init, flush/stop at Spot
   shutdown) — reuses `AsyncJsonlSink.start()` / `stop()`.

## 8. Tests

- `test_spot_incident_log.py`: unit tests for all five transitions using
  `AsyncJsonlSink.write_sync` or a fake sink collecting emitted records. Asserts
  `incident_id` is shared across all records for one incident, fields are
  present and correctly typed, and `exception_repr` has paths scrubbed.
- `test_async_jsonl_sink.py`: add no-purge test — `retention_days=0` leaves
  files older than 30 days untouched.
- `test_kaine_toml.py`: shipped `[spot.incident_log].enabled = true`, and Spot
  still ships with `[spot].enabled = false`.
