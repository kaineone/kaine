# Design: research-event-log

## Problem

The KAINE event bus (`kaine/bus/`) is a capped Redis Streams ring buffer
(`default_maxlen = 100 000`, approximate-trim per `config/kaine.toml [bus]`).
Events are trimmed within minutes to hours of publication and Redis persistence
is disabled. Nothing archives them, so post-hoc longitudinal analysis —
correlating affect trajectories with prediction-error trends, action-success
rates, or individuation divergence across sessions — is impossible once the
ring wraps. A follow-up paper needs a durable record.

---

## Reusable infrastructure

This change builds entirely on existing infra and adds no new primitives.

### `AsyncJsonlSink` (`kaine/evaluation/sink.py:27`)

Async/non-blocking JSONL writer: writes go through an `asyncio.Queue` and are
drained by a background task, so the cognitive cycle is never blocked on disk
I/O. Features daily rotation, retention pruning (default 30 d), and per-line
AES-256-GCM encryption via `get_state_encryptor()` (`kaine/security/crypto.py`).
Records are free-form dicts; the convention is a `ts` ISO-8601 UTC field on
every record. Drops oldest on full queue.

### Observer framework (`kaine/evaluation/_base.py`)

- `StreamSubscriberObserver`: follows a single named bus stream with a
  cursor; `_run()` polls, updates the cursor, calls `handle(entry_id, event)`.
- `WorkspaceSubscriberObserver`: follows `workspace.broadcast` via the canonical
  `bus.subscribe_workspace()` path, yielding decoded snapshot dicts to `handle()`.
- `BaseObserver`: lifecycle (`start()`, `stop()`), crash-safe `_safe_run()`.

`SidecarRegistry` (`kaine/evaluation/registry.py`) constructs all enabled
observers, manages sink lifecycles, and exposes observers for Nexus diagnostics.
The `WelfareObserver` (`kaine/evaluation/observers/welfare_observer.py`) is the
canonical reference for a multi-stream, multi-cursor observer that subscribes to
a curated stream set and writes to a single `AsyncJsonlSink`.

### Privacy mechanisms (reuse, do not reinvent)

| Mechanism | Source | What it strips |
|---|---|---|
| `PrivacyFilter.filter_for_diagnostics()` | `kaine/nexus/privacy.py:56` | `CONTENT_FIELDS`: text, body, content, internal\_speech, belief\_text, memory\_text, affect\_reason, transcription, user\_input, faithful\_rendering |
| `redact_content` / `_REDACTED_DROP = {"text"}` | `kaine/evaluation/observers/replay_observer.py:31` | `text` key from replay payload |
| Praxis `_sanitize()` / `_FORBIDDEN_KEYS = {"content", "body", "stdout"}` | `kaine/modules/praxis/audit_log.py:64` | content/body/stdout from action summaries |
| `DENY_PATTERNS` / `_deny_check()` + `METRICS_ONLY_DIRS` allowlist | `kaine/research/submission.py:47,69,141` | Structural export gate: only named subdirs under `data/evaluation/` enter a metrics bundle |

Every record written by `ResearchEventObserver` passes through
`PrivacyFilter.filter_for_diagnostics()` first (strips `CONTENT_FIELDS`), then
applies any additional per-event-type redactions from the taxonomy table below.

---

## Part 1: Curated research event log

### Architecture

```
Bus streams  ──┐
               ▼
   ResearchEventObserver          (new, kaine/evaluation/observers/research_event_observer.py)
      Multi-cursor poll loop       (mirrors WelfareObserver pattern)
      per-event taxonomy dispatch  (see table below)
      PrivacyFilter + redact       (reused, applied before every write)
               │
               ▼
   AsyncJsonlSink "research_events"
      data/evaluation/research_events/
      AES-256-GCM per-line encryption
      daily rotation, 30-d retention
               │
               ▼
   METRICS_ONLY_DIRS  ──► research bundle (export-eligible)
```

The observer also subscribes to `workspace.broadcast` via
`WorkspaceSubscriberObserver` for workspace metadata records. The multi-stream
polling approach (one observer, multiple cursors) mirrors `WelfareObserver`
exactly.

### Config gate

New `[research_event_log]` block in `config/kaine.toml`, ships disabled.
Independent of `[evaluation].enabled`.

```toml
[research_event_log]
# Curated, privacy-filtered research event log. Ships disabled.
# Independent of [evaluation].enabled. Add "research_events" to the metrics
# bundle allowlist (METRICS_ONLY_DIRS) automatically when enabled.
enabled = false
# Directory for the curated log sink (under data/evaluation/).
log_dir = "data/evaluation/research_events"
# Retention in days (mirrors evaluation.paths.retention_days).
retention_days = 30
```

New `ResearchEventLogConfig` dataclass in `kaine/evaluation/config.py` reads
this block via `from_mapping()`.

### METRICS_ONLY_DIRS addition

`kaine/research/submission.py`: add `"research_events"` to `METRICS_ONLY_DIRS`.
This is the **sole mechanism** that makes the curated log export-eligible.
The raw archive (`state/research/raw_bus_archive/`) is structurally excluded
because it lives outside `data/evaluation/`.

### Curated taxonomy

Every record includes: `ts` (ISO-8601 UTC), `event_type`, `source`.
Fields marked `tick_index` / `incident_id` are included when present in the
event payload.

| Family | Bus event type(s) | Fields logged | Fields NEVER logged |
|---|---|---|---|
| **Cycle** | `cycle.tick` | slip\_ms, wall\_duration\_ms, target\_duration\_ms, is\_experiential | raw timestamps, internal state |
| | `cycle.rates` | processing\_hz, experiential\_hz, tick\_count | — |
| | `workspace.broadcast` | tick\_index, inhibited (bool), salience\_scores dict, per-entry: {source, type, salience, causal\_parent} | payload of any entry |
| | `volition.intent.*` | intent kind, about-tag, effector | content, params text, full intent body |
| **Prediction/precision** | `soma.report` | prediction\_error, wellness, fatigue\_value, alerts-as-boolean-flags | raw vitals |
| | `topos.report` | prediction\_error, horizon | raw latents, scene data |
| | `phantasia.world_error` | error (scalar) | latent state, scenario content |
| | `nous.belief`, `nous.policy`, `nous.error`, `nous.timeout` | kind (label), frequency, confidence, expected\_free\_energy, elapsed\_ms | belief text, policy content |
| **Affect/motivation** | `thymos.state` | valence, arousal, dominance, drives dict (name→value), emotion\_category | affect\_reason |
| | `thymos.emotion` | category, scores dict, norm\_compatibility\_available (bool) | — |
| | `thymos.drive` | drive (name), value | — |
| | `thymos.goal` | action (label), goal\_id | description, content |
| **Perception (derived)** | `audition.emotion` | category, confidence, scores dict | raw audio, transcript text |
| | `audition.prosody` | f0\_mean, f0\_std, f0\_voiced\_frac, rms\_mean, rms\_std, tempo\_bpm | raw audio |
| | `topos.scene_change` | change\_scalar | raw frames, latents |
| **Memory/sleep** | `mnemos.recall` | memory\_ids list, max\_affect\_intensity, selection\_scores list | text |
| | `mnemos.replay` | memory\_ids list, max\_affect\_intensity, selection\_scores list | text (via `_REDACTED_DROP`) |
| | `hypnos.sleep.started` | trigger (label), fatigue\_at\_trigger | — |
| | `hypnos.sleep.completed` | phases\_completed list, replay\_count, consolidation\_summary\_counts dict | replay content |
| | fork/merge events | event\_type, snapshot\_id, parent\_ids, strategy | — |
| **Self/social** | `eidolon.drift` | drift\_scalar, significant (bool) | self\_model doc |
| | `empatheia.agent_model` | agent\_label, familiarity\_scalar | agent content, stored model |
| | `empatheia.social_error` | agent\_label, error\_magnitude | — |
| **Action** | `praxis.action` | action\_family, effector, success (bool), duration\_ms | content, body, stdout (via `_sanitize`) |
| **Safety/ops** | Spot incidents | incident\_id (cross-link to `spot-incident-log`), module\_name, incident\_kind, restart\_count | internal stack trace text |
| | welfare gray-zone events | gray\_zone\_event (label), numeric scalars | — |
| | individuation divergence | divergence\_scalar, significant (bool) | preference battery content |
| | `perception.locus.changed` | locus, changed\_by | — |
| | `perception.locus.denied` | locus\_requested, denied\_by, reason\_label | — |
| | `mundus.proprio` | avatar\_position\_hash (opaque scalar), region\_label | coordinates, operator host/IP |
| | `mundus.scene` | object\_count, scene\_change\_scalar | visual content, raw frames |
| | `mundus.notice` | notice\_kind (label) | content |

`audition.transcription` text is **never** logged. `mundus.visual.raw` frames
are **never** logged.

---

## Part 2: Optional local-only raw bus archive

### Rationale and isolation

Some research questions require verbatim event payloads (e.g. checking whether
transcripts correlate with predicted emotion categories under specific operating
conditions). This data cannot be made export-eligible without full consent review,
so the design isolates it structurally and behind a double gate.

### Architecture

```
All <module>.out streams ──┐
                           ▼
   RawBusArchiveConsumer           (new, kaine/evaluation/observers/raw_bus_archive_consumer.py)
      StreamSubscriberObserver     (cursor-follow pattern, one per stream)
      Attestation gate check       (BundleTierError-mirror; refuses to start if
                                    entity_privacy_attested or bystander_consent_attested is false)
                           │
                           ▼
   AsyncJsonlSink "raw_bus_archive"
      state/research/raw_bus_archive/      ← OUTSIDE data/evaluation/
      AES-256-GCM per-line encryption
      daily rotation, 30-d retention
```

The sink directory (`state/research/raw_bus_archive/`) is structurally outside
`data/evaluation/`, so it is physically impossible for `build_research_bundle()`'s
metrics-tier loop (which only reads from `eval_root = data/evaluation/`) to
include it in an export bundle. `DENY_PATTERNS` provides belt-and-suspenders.

### Config gate

```toml
[research_event_log.raw_archive]
# LOCAL-ONLY raw bus archive. NEVER export-eligible (writes outside data/evaluation/).
# Ships disabled. Requires BOTH enabled = true AND both attestation flags = true.
enabled = false
# Both flags must be true before the consumer will start (mirrors BundleTierError
# attestation in kaine/research/submission.py:196-206).
entity_privacy_attested = false
bystander_consent_attested = false
# Storage path (MUST remain outside data/evaluation/).
archive_dir = "state/research/raw_bus_archive"
retention_days = 30
```

### Attestation enforcement

`RawBusArchiveConsumer.start()` checks both attestation flags before starting
any stream cursor. If either is false, it raises `RawArchiveAttestationError`
(a `ValueError` subclass mirroring `BundleTierError`) and logs at ERROR level.
This mirrors the pattern at `kaine/research/submission.py:196-206`.

The consumer is explicit that:

- The raw archive never leaves the host.
- It is never export-eligible.
- It exists only because the operator explicitly opted in with attestation.

### Non-interference

- The raw archive consumer does NOT filter or transform records — the point is
  verbatim capture before MAXLEN trims events.
- It has no interaction with `METRICS_ONLY_DIRS`, `DENY_PATTERNS`, or the
  research bundle builder beyond relying on structural path isolation.
- Its lifecycle (`start()`/`stop()`) is managed by `SidecarRegistry` as a
  peer of the curated observer, under the separate `raw_archive` config gate.

---

## Ambiguities resolved during design

1. **Independence from `[evaluation].enabled`**: The curated log is wired through
   `SidecarRegistry` for lifecycle consistency but checked against its own
   `ResearchEventLogConfig.enabled` flag, not `EvaluationConfig.enabled`. An
   install with the evaluation sidecar disabled can still run the research event
   log (or vice-versa).

2. **`incident_id` linking to `spot-incident-log`**: The `spot-incident-log`
   change (sibling OpenSpec) will own the Spot incident record schema. The
   research event log references Spot incident records by `incident_id` only —
   it does not duplicate Spot's full record. The cross-link is documented in both
   changes.

3. **`mundus.proprio` coordinates**: Avatar grid coordinates are operator-location
   adjacent (the operator controls the avatar's body). The design logs only an
   opaque position hash (or omits coordinates entirely), not raw `x/y/z`. Region
   labels are acceptable per the existing privacy policy (the operator's region is
   not a bystander).

4. **`volition.intent.*` stream**: If this stream does not yet exist in the
   shipped bus schema, the observer silently skips it (the multi-cursor loop does
   not error on an absent stream; `read_entries` returns empty). Implementation
   adds it to the subscription list as a forward-compatible no-op until the stream
   exists.

5. **Workspace broadcast salience scores**: The workspace broadcast payload
   contains the scored entry list. The observer extracts per-entry metadata
   (source, type, salience, causal\_parent) from the broadcast snapshot dict but
   never the entry payload field.
