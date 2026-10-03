# research-event-log Specification

## Purpose
The curated, content-free longitudinal record of a research run — the only stream export-eligible as a metrics bundle.

## Requirements

### Requirement: Opt-in durable research event log

The system SHALL provide a `ResearchEventObserver` that subscribes to a
curated allowlist of bus streams, applies privacy transforms, and writes
encrypted records to an `AsyncJsonlSink` named `research_events` under
`data/evaluation/research_events/`.

The observer SHALL be gated behind a `[research_event_log] enabled = false`
config block that ships with `enabled = false` and is independent of
`[evaluation].enabled`.

The `data/evaluation/research_events/` directory SHALL be added to
`METRICS_ONLY_DIRS` in `kaine/research/submission.py`, making it export-eligible
in a metrics research bundle. No other mechanism makes it eligible.

Every record written by the observer SHALL carry: `ts` (ISO-8601 UTC string),
`event_type`, `source`, and `tick_index` or `incident_id` when present in the
originating event payload.

Records SHALL contain only numeric or categorical payload values drawn from the
curated taxonomy defined in `design.md`. No record SHALL contain free-text
content of any kind.

#### Scenario: Curated log is disabled by default

- **WHEN** `config/kaine.toml` is unmodified (shipped state)
- **THEN** `ResearchEventLogConfig.enabled` SHALL be `false`
- **AND** `ResearchEventObserver` SHALL NOT be constructed or started
- **AND** no `data/evaluation/research_events/` sink SHALL be opened

#### Scenario: Curated log activates when enabled

- **WHEN** `[research_event_log] enabled = true` is set in config
- **AND** the cognitive cycle starts
- **THEN** `ResearchEventObserver` SHALL be constructed and started by
  `SidecarRegistry`
- **AND** it SHALL subscribe to at least the curated streams listed in
  `design.md`

#### Scenario: Curated log is independent of evaluation sidecar

- **WHEN** `[evaluation] enabled = false`
- **AND** `[research_event_log] enabled = true`
- **THEN** `ResearchEventObserver` SHALL start and write records
- **WHEN** `[evaluation] enabled = true`
- **AND** `[research_event_log] enabled = false`
- **THEN** `ResearchEventObserver` SHALL NOT start

#### Scenario: Curated log is export-eligible

- **WHEN** `build_research_bundle(tier="metrics")` is called
- **THEN** files under `data/evaluation/research_events/` SHALL be included
  in the bundle (subject to normal deny-pattern checks)

---

### Requirement: Privacy-preserving record transform

Every record written by `ResearchEventObserver` SHALL pass through
`PrivacyFilter.filter_for_diagnostics()` before field extraction, stripping all
`CONTENT_FIELDS` (`text`, `body`, `content`, `internal_speech`, `belief_text`,
`memory_text`, `affect_reason`, `transcription`, `user_input`,
`faithful_rendering`) from the raw event payload.

Additionally, per-event-type redactions SHALL be applied as specified in the
taxonomy table in `design.md`. The following MUST NEVER appear in any written
record, regardless of what the bus event carries:

- Raw audio or raw video frames (`mundus.visual.raw`, PCM samples)
- `audition.transcription` text (the verbatim speech transcript)
- The Lingua intent log content or intent params text
- Mnemos/Qdrant memory text bodies (`text` field in `mnemos.recall` /
  `mnemos.replay`)
- The Eidolon self-model document (only drift scalars are logged)
- Empatheia agent model content (only familiarity scalar is logged)
- Conversation turn content (any form of user input or entity response text)
- Praxis action content, body, or stdout (stripped by `_sanitize()`)
- Operator hostname, IP address, or voice name

#### Scenario: CONTENT_FIELDS are absent from every record

- **WHEN** a bus event whose payload contains a `CONTENT_FIELDS` key (e.g.
  `text`, `content`, `affect_reason`) is received
- **THEN** the written record SHALL NOT contain that key
- **AND** the value SHALL NOT appear anywhere in the record dict

#### Scenario: audition.transcription is never logged

- **WHEN** an `audition.transcription` event arrives on the bus
- **THEN** `ResearchEventObserver` SHALL write no record for it

#### Scenario: mundus.visual.raw frames are never logged

- **WHEN** a `mundus.visual.raw` event arrives on the bus
- **THEN** `ResearchEventObserver` SHALL write no record for it

#### Scenario: mnemos replay text is redacted

- **WHEN** a `mnemos.replay` event payload contains a `text` field
- **THEN** the written record SHALL contain `memory_ids` and
  `max_affect_intensity` but SHALL NOT contain `text`

#### Scenario: praxis action content is stripped

- **WHEN** a `praxis.action` event payload contains `content`, `body`, or
  `stdout`
- **THEN** the written record SHALL NOT contain those fields (stripped via
  `_sanitize()`)
- **AND** the record SHALL contain `action_family`, `effector`, `success`,
  `duration_ms`

---

### Requirement: Non-blocking capture

The research event log SHALL never block the cognitive cycle. All writes SHALL
be performed through `AsyncJsonlSink.write()`, which queues entries
asynchronously and drains them via a background task (matching the pattern at
`kaine/evaluation/sink.py:27`).

When the sink queue is full, the oldest queued entry SHALL be dropped in favour
of the newest. The drop SHALL be counted and available for diagnostics.

`ResearchEventObserver` SHALL be a `BaseObserver` subclass with a `start()` /
`stop()` lifecycle managed by `SidecarRegistry`, and SHALL run in its own
`asyncio.Task` separate from the cognitive loop.

#### Scenario: Observer runs as a separate asyncio task

- **WHEN** `SidecarRegistry.start()` is called with the research event log
  enabled
- **THEN** `ResearchEventObserver` SHALL run in an asyncio task named
  `sidecar-research_event_log`
- **AND** the cognitive cycle tick SHALL not await the observer's write path

#### Scenario: Queue-full drops oldest entry

- **WHEN** the sink queue is at `maxsize` and a new record arrives
- **THEN** the oldest entry SHALL be dropped
- **AND** `sink.dropped_count` SHALL increment

---

### Requirement: Optional local-only raw archive behind attestation

The system SHALL provide a `RawBusArchiveConsumer` that archives verbatim bus
events to `state/research/raw_bus_archive/`. This archive SHALL be gated behind
BOTH `[research_event_log.raw_archive] enabled = true` AND both attestation
flags (`entity_privacy_attested = true`, `bystander_consent_attested = true`)
set explicitly in config.

The raw archive SHALL be written to a path outside `data/evaluation/` so it
is structurally impossible for the metrics bundle builder to include it.

The raw archive SHALL be encrypted at rest (same `AsyncJsonlSink` +
`StateEncryptor` mechanism as the curated log).

If the attestation flags are not both `true`, `RawBusArchiveConsumer.start()`
SHALL raise `RawArchiveAttestationError` and log at `ERROR` level. The consumer
SHALL NOT start in this state.

The raw archive is never export-eligible. This SHALL be stated explicitly in the
module docstring of `raw_bus_archive_consumer.py`.

#### Scenario: Raw archive is disabled by default

- **WHEN** `config/kaine.toml` is unmodified (shipped state)
- **THEN** `RawArchiveConfig.enabled` SHALL be `false`
- **AND** `RawBusArchiveConsumer` SHALL NOT be constructed or started

#### Scenario: Raw archive refuses to start without both attestations

- **WHEN** `[research_event_log.raw_archive] enabled = true`
- **AND** `entity_privacy_attested = false` (regardless of bystander flag)
- **THEN** `RawBusArchiveConsumer.start()` SHALL raise `RawArchiveAttestationError`

- **WHEN** `[research_event_log.raw_archive] enabled = true`
- **AND** `bystander_consent_attested = false` (regardless of entity flag)
- **THEN** `RawBusArchiveConsumer.start()` SHALL raise `RawArchiveAttestationError`

#### Scenario: Raw archive starts with full attestation

- **WHEN** `[research_event_log.raw_archive] enabled = true`
- **AND** `entity_privacy_attested = true`
- **AND** `bystander_consent_attested = true`
- **THEN** `RawBusArchiveConsumer` SHALL start and write verbatim event records
  to the configured archive directory

#### Scenario: Raw archive is never included in a metrics bundle

- **WHEN** `build_research_bundle(tier="metrics")` is called
- **AND** `state/research/raw_bus_archive/` contains files
- **THEN** NO file from `state/research/raw_bus_archive/` SHALL appear in the
  bundle (the metrics-tier loop only reads from `data/evaluation/`)

### Requirement: Research records are kept by default

`retention_days` SHALL ship as `0` in `[evaluation.paths]`,
`[research_event_log]` and `[research_event_log.raw_archive]`, and the matching
configuration dataclasses SHALL default to `0` when the key is absent. A value of
`0` or less SHALL disable the age-based purge, so no daily file is deleted
automatically. A positive value SHALL still purge daily files older than that
many days. Disk space is checked before boot by the pre-boot disk-free rows
instead of by deleting records.

#### Scenario: Shipped config keeps records

- **WHEN** the committed `config/kaine.toml` is loaded
- **THEN** all three `retention_days` values are `0`

#### Scenario: Absent key keeps records

- **WHEN** the evaluation paths, research event log and raw archive configs are
  built from empty tables
- **THEN** each `retention_days` is `0`

#### Scenario: An old research file survives a sink start

- **WHEN** a sink built with `retention_days = 0` starts in a directory holding a
  daily file older than 30 days
- **THEN** that file remains on disk

### Requirement: External utterances are recorded locally, and inner speech never
When `[research_event_log.external_utterances].enabled` is true, the cycle SHALL record each `external_speech` event from `lingua.external`, with its text and timestamps, through the encrypted JSONL sink under `state/research/external_utterances/`. It SHALL NOT subscribe to `lingua.internal`, SHALL NOT record any `internal_speech` event, and SHALL NOT record `user_input`. The log SHALL NOT be export-eligible.

#### Scenario: An inner thought is not recorded
- **WHEN** Lingua publishes an `internal_speech` event while the log is enabled
- **THEN** nothing about it is written to the external-utterance log

#### Scenario: An utterance is recorded
- **WHEN** Lingua publishes an `external_speech` event while the log is enabled
- **THEN** its text and timestamps are written to the external-utterance log

### Requirement: What Nexus displays is recorded for each run
When `[research_event_log.nexus_record].enabled` is true, the cycle SHALL record every event on the streams Nexus displays, after the same privacy filter Nexus applies, through the encrypted JSONL sink under `data/nexus_record/`. The record SHALL contain nothing that Nexus's filtered feed does not contain. It SHALL NOT be export-eligible.

#### Scenario: The record matches the display
- **WHEN** an event on a displayed stream is published during a run with the record enabled
- **THEN** the record holds the same filtered payload the Nexus bridge sends

#### Scenario: Filtered content stays out
- **WHEN** an event carries a field the privacy filter removes
- **THEN** that field does not appear in the record

### Requirement: The diagnostics privacy filter removes numeric vectors
The diagnostics privacy filter SHALL remove, at every nesting depth, every field named in its vector-field set (`latent`, `peripheral`, `foveal`, `temporal_context`, `feature_vector`) and every list or tuple of 16 or more numbers (booleans excluded) whose key is not a reviewed non-embedding key (`saliences`, `step_magnitudes`). No perceptual or latent embedding SHALL reach the Nexus stream, the Nexus record or any other surface that uses the filter.

#### Scenario: A vision report
- **WHEN** a `topos.report` carrying `latent`, `peripheral` and `foveal` passes the filter
- **THEN** all three are removed and its scalar fields, `fovea` and `predicted_fovea` are kept

#### Scenario: A short test latent
- **WHEN** a payload carries `latent` with four numbers
- **THEN** it is removed

#### Scenario: An unnamed embedding
- **WHEN** a payload carries a field `embedding_x` holding 64 numbers
- **THEN** it is removed

#### Scenario: Small and reviewed lists survive
- **WHEN** a payload carries `scores` with 5 numbers and `saliences` with 40 numbers
- **THEN** both are kept
