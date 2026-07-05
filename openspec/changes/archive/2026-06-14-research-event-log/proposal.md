## Why

The KAINE event bus is a capped Redis Streams ring buffer (`MAXLEN ~100 000`,
approximate-trim, no Redis persistence). Events are trimmed within minutes to
hours of publication. Nothing currently archives them to durable storage, so
session-spanning research questions — longitudinal affect trajectories,
within-session prediction-error patterns, action distributions across operating
conditions — cannot be answered from post-hoc log analysis. A follow-up paper
needs a durable, privacy-safe event history that is: (a) encrypted at rest,
(b) selective enough to never capture raw sense data or conversation content,
(c) export-eligible via the existing `METRICS_ONLY_DIRS` allowlist, and (d)
ships disabled so it respects the all-off first-boot guard.

## What Changes

### Part 1 — Curated research event log (default offering, export-eligible)

A new `ResearchEventObserver` — modelled on `WelfareObserver` — subscribes to
a curated allowlist of bus streams and writes privacy-filtered records to a new
`AsyncJsonlSink` named `research_events` under `data/evaluation/research_events/`.
That directory is added to `METRICS_ONLY_DIRS` in `kaine/research/submission.py`,
making it export-eligible in a metrics research bundle.

The observer is gated behind a new `[research_event_log] enabled = false` config
block in `config/kaine.toml` (ships disabled). It is independent of
`[evaluation].enabled`: the evaluation sidecar and the research event log can
be enabled or disabled separately.

Every record carries `ts` (ISO-8601 UTC), `event_type`, `source`, and
`tick_index`/`incident_id` where present, plus numeric/categorical payload
only. Before writing, every record passes through `PrivacyFilter.filter_for_diagnostics()`
and the `redact_content`/`_sanitize()` helpers, stripping all content fields.

The curated taxonomy covers seven event families:

- **Cycle/workspace:** `cycle.tick`, `cycle.rates`, workspace broadcast metadata
  (tick index, inhibition flag, salience scores, per-entry source/type/salience/
  causal parent — never payload text), `volition.intent.*` (kind + about-tag +
  effector — never content/params text)
- **Prediction/precision:** `soma.report`, `topos.report`, `phantasia.world_error`,
  `nous.belief/policy/error/timeout` (scalars/labels only)
- **Affect/motivation:** `thymos.state` (VAD + drives + emotion category),
  `thymos.emotion`, `thymos.drive`, `thymos.goal` (action + id, not description)
- **Perception (derived only):** `audition.emotion`, `audition.prosody` (6 numeric
  scalars), topos scene-change scalar — never raw audio/frames, never
  `audition.transcription` text
- **Memory/sleep:** `mnemos.recall/replay` (memory IDs + affect intensity +
  selection scores, text redacted), `hypnos.sleep.started/completed` (+ count
  summaries), fork/merge events
- **Self/social:** `eidolon.drift` (drift scalar + significant bool — not the
  self-model doc), `empatheia.agent_model` (familiarity scalar — not agent
  content), `empatheia.social_error` (error magnitude)
- **Action:** `praxis.action` (action\_family, effector, success, duration\_ms —
  `_sanitize` strips content/body/stdout)
- **Safety/ops:** Spot incidents cross-linked by `incident_id` to the sibling
  `spot-incident-log` change, welfare gray-zone events, individuation divergence
  scalars, `perception.locus.changed/denied`, `mundus.proprio/scene/notice`
  metadata — never `mundus.visual.raw` frames

### Part 2 — Optional local-only raw bus archive (richer, NOT export-eligible)

A separate `RawBusArchiveConsumer` uses the `StreamSubscriberObserver`
cursor-follow pattern over all `<module>.out` streams to durably archive raw
events before MAXLEN trims them, for deep local analysis.

This archive contains conversation content and transcripts, so:

- It writes to `state/research/raw_bus_archive/` — outside `data/evaluation/` —
  so it can never be picked up by the metrics bundle allowlist.
- It is encrypted at rest via `StateEncryptor`.
- It is gated behind **both** `[research_event_log.raw_archive] enabled = false`
  AND an explicit attestation (mirroring the `BundleTierError` pattern in
  `kaine/research/submission.py:196-206`): `entity_privacy_attested` and
  `bystander_consent_attested` must both be set to `true` in config before the
  consumer will start.

The raw archive never leaves the host, is never export-eligible, and exists only
because the operator explicitly opted in with attestation.

## Capabilities

### New Capabilities

- `research-event-log`: durable privacy-safe curated research event log and
  optional local-only raw bus archive, both ships-disabled.

### Modified Capabilities

<!-- none -->

## Impact

- **Config (edit):** `config/kaine.toml` — new `[research_event_log]` and
  `[research_event_log.raw_archive]` blocks (ships disabled)
- **Code (new):** `kaine/evaluation/config.py` — `ResearchEventLogConfig` +
  `RawArchiveConfig` dataclasses; `kaine/evaluation/observers/research_event_observer.py`
  — curated taxonomy observer; `kaine/evaluation/observers/raw_bus_archive_consumer.py`
  — raw archive consumer with attestation gate
- **Code (edit):** `kaine/research/submission.py` — add `"research_events"` to
  `METRICS_ONLY_DIRS`; `kaine/evaluation/registry.py` — wire
  `ResearchEventObserver` and `RawBusArchiveConsumer` under their new config gates
- **Tests:** `tests/test_research_event_log.py` (new file covering taxonomy
  transforms, privacy filter wiring, attestation gate, METRICS_ONLY_DIRS
  membership, and raw archive isolation)
- **Safety:** ships disabled; no module enables; respects the all-off first-boot
  guard; raw archive is doubly-gated (flag + attestation) and structurally
  isolated from the export allowlist
