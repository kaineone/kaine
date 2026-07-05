## ADDED Requirements

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
