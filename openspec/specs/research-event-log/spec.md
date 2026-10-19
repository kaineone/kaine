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

- Raw audio or raw video frames (`embodiment.visual.raw`, PCM samples)
- `audition.transcription` text (the verbatim speech transcript)
- The language module's intent log content or intent params text
- the episodic memory module's Qdrant memory text bodies (`text` field in `episodic_memory.recall` /
  `episodic_memory.replay`)
- The self-model document (only drift scalars are logged)
- The social cognition module's agent model content (only familiarity scalar is logged)
- Conversation turn content (any form of user input or entity response text)
- The effectors module's action content, body, or stdout (stripped by `_sanitize()`)
- Operator hostname, IP address, or voice name

#### Scenario: CONTENT_FIELDS are absent from every record

- **WHEN** a bus event whose payload contains a `CONTENT_FIELDS` key (e.g.
  `text`, `content`, `affect_reason`) is received
- **THEN** the written record SHALL NOT contain that key
- **AND** the value SHALL NOT appear anywhere in the record dict

#### Scenario: audition.transcription is never logged

- **WHEN** an `audition.transcription` event arrives on the bus
- **THEN** `ResearchEventObserver` SHALL write no record for it

#### Scenario: embodiment.visual.raw frames are never logged

- **WHEN** a `embodiment.visual.raw` event arrives on the bus
- **THEN** `ResearchEventObserver` SHALL write no record for it

#### Scenario: episodic memory replay text is redacted

- **WHEN** a `episodic_memory.replay` event payload contains a `text` field
- **THEN** the written record SHALL contain `memory_ids` and
  `max_affect_intensity` but SHALL NOT contain `text`

#### Scenario: effectors action content is stripped

- **WHEN** a `effectors.action` event payload contains `content`, `body`, or
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
When `[research_event_log.external_utterances].enabled` is true, the cycle SHALL record each `external_speech` event from `language.external`, with its text and timestamps, through the encrypted JSONL sink under `state/research/external_utterances/`. It SHALL NOT subscribe to `language.internal`, SHALL NOT record any `internal_speech` event, and SHALL NOT record `user_input`. The log SHALL NOT be export-eligible.

#### Scenario: An inner thought is not recorded
- **WHEN** the language module publishes an `internal_speech` event while the log is enabled
- **THEN** nothing about it is written to the external-utterance log

#### Scenario: An utterance is recorded
- **WHEN** the language module publishes an `external_speech` event while the log is enabled
- **THEN** its text and timestamps are written to the external-utterance log

### Requirement: What Dashboard displays is recorded for each run
When `[research_event_log.dashboard_record].enabled` is true, the cycle SHALL record every event on the streams the dashboard displays, after the same privacy filter the dashboard applies, through the encrypted JSONL sink under `data/nexus_record/`. The record SHALL contain nothing that the dashboard's filtered feed does not contain. It SHALL NOT be export-eligible.

#### Scenario: The record matches the display
- **WHEN** an event on a displayed stream is published during a run with the record enabled
- **THEN** the record holds the same filtered payload the dashboard bridge sends

#### Scenario: Filtered content stays out
- **WHEN** an event carries a field the privacy filter removes
- **THEN** that field does not appear in the record

### Requirement: The diagnostics privacy filter removes numeric vectors
The diagnostics privacy filter SHALL remove, at every nesting depth, every field named in its vector-field set (`latent`, `peripheral`, `foveal`, `temporal_context`, `feature_vector`) and every list or tuple of 16 or more numbers (booleans excluded) whose key is not a reviewed non-embedding key (`saliences`, `step_magnitudes`). No perceptual or latent embedding SHALL reach the dashboard stream, the dashboard record or any other surface that uses the filter.

#### Scenario: A vision report
- **WHEN** a `vision.report` carrying `latent`, `peripheral` and `foveal` passes the filter
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

### Requirement: The research log carries the planned test's fields
The curated research log SHALL record, for each predictive processor report, its `alert` flag and, where the processor conditions on the broadcast, its `context_gain` and `context_age_s`; it SHALL record Audition's `audition.perception` reports with their numeric fields; and it SHALL record each broadcast's `access_threshold`. It SHALL NOT record the playlist item title.

#### Scenario: An acoustic report is logged with its information gain
- **WHEN** Audition publishes `audition.perception` with `context_gain` 0.12, `alert` false and an `item` title
- **THEN** the research record has `context_gain` 0.12 and `alert` false and no `item`

#### Scenario: A broadcast record carries the access threshold
- **WHEN** a broadcast with metadata `access_threshold` 0.35 is recorded
- **THEN** the workspace record has `access_threshold` 0.35

### Requirement: The research log carries the paired evaluations
The curated research log SHALL copy `null_prediction_error` and `mean_prediction_error` from `vision.report`, `interoception.report` and `audition.perception`, and the post-run range sweep SHALL require both to be non-negative.

#### Scenario: A processor report is logged with its paired evaluations
- **WHEN** the interoception module publishes a report with `context_gain` -0.05, `null_prediction_error` 0.5 and `mean_prediction_error` 0.8
- **THEN** the research record carries all three values

### Requirement: The workspace record names the arm
The research log's workspace record SHALL copy `arm` from the broadcast metadata when present, so the records of each run say which arm of the planned ablation produced them.

#### Scenario: A matched broadcast is recorded with its arm
- **WHEN** a broadcast with metadata `arm` "matched" is recorded
- **THEN** the workspace record has `arm` "matched"

### Requirement: The curated log records sensor advisories with an exact allowlist
The curated research event log SHALL record `welfare.blind_sensor`, `welfare.blind_sensor_cleared`, `welfare.sensor_silent` and `welfare.sensor_silent_cleared` events from `welfare.out`. A record SHALL carry the `processor` label only when it is one of the known processor labels. A blind-sensor record SHALL carry only the numeric fields `undefined_samples`, `undefined_seconds`, `blind_sensor_samples`, `blind_sensor_duration_s` and `blind_sensor_count`, and a silent-sensor record only `silent_seconds`, `sensor_silent_duration_s` and `sensor_silent_count`, each only when it is an int or float and not a boolean. Every other payload field SHALL be dropped.

#### Scenario: Stray fields and unknown labels are dropped
- **WHEN** a `welfare.blind_sensor_cleared` event carries an unknown processor label, a boolean `undefined_samples` and a content field
- **THEN** its record has no `processor`, no `undefined_samples` and no content field, and keeps the numeric `blind_sensor_count`

### Requirement: Reports name the broadcast that preceded their prediction
The vision module (`vision.report`), the audition module (`audition.perception`) and the interoception module (`interoception.report`) SHALL put on every report `prediction_broadcast_tick`, the tick index of the latest broadcast the processor had received, accessed or inhibited, when it formed the prediction the report scores, and `prediction_context_age_s`, the age in entity seconds of the context that prediction used, read when the prediction was formed. Both SHALL be null when the report scores no prediction (the first report, or the first after a skipped reading), and `prediction_context_age_s` SHALL be null when the processor held no context when forming the prediction. The curated research log SHALL copy both fields, and the range sweep SHALL bound both below by 0. The contrast at threshold groups reports by the broadcast whose receipt preceded the formation of their prediction and bins them by the age of the context they used (paper Appendix A.8).

#### Scenario: An inhibited broadcast arrives between two reports
- **WHEN** a processor forms a prediction after receiving accessed broadcast 7, then receives inhibited broadcast 8, then reports
- **THEN** the report carries `prediction_broadcast_tick` 7 and the context age read when the prediction was formed, and the next report carries `prediction_broadcast_tick` 8

#### Scenario: A skipped reading
- **WHEN** a processor skips a non-finite reading
- **THEN** the next report carries `prediction_broadcast_tick` and `prediction_context_age_s` null

### Requirement: The research log identifies tone events and broadcast members
The curated research log SHALL put on each `audition.emotion` record the bus entry id of the event (`entry_id`) and copy `tone_error_ratio`, `tone_rule`, `classified` and `alert`, and SHALL put `entry_id` on each member of a `workspace.broadcast` record. A tone event is accessed content when it is a member of a broadcast that is not inhibited and its score in the broadcast's score table reaches the access threshold (paper A.1); with these fields the tone analysis decides that from the log, and it refuses a broadcast in which two members share an entry id, since the cycle keys scores by entry id alone. The range sweep SHALL bound `tone_error_ratio` on `audition.emotion` below by 0.

#### Scenario: A tone event is accessed
- **WHEN** a broadcast that is not inhibited has as a member the tone event with entry id `5-0` and its score reaches the access threshold
- **THEN** the broadcast record's member carries `entry_id` `5-0` and the `audition.emotion` record carries the same `entry_id`

### Requirement: Tone records carry the stream-qualified id
The research log's `audition.emotion` record SHALL carry in `entry_id` the event's stream-qualified id `<stream>:<entry_id>`, the id the cycle gives the event as a workspace candidate and the `entry_id` of the event as a member of a `workspace.broadcast` record. This replaces the bare bus entry id that change `tone-analysis-inputs` put there.

#### Scenario: A tone event's id matches its member id
- **WHEN** the research log records an `audition.emotion` event read from `audition.out` with bus id `5-0`
- **THEN** the record's `entry_id` is `audition.out:5-0`

### Requirement: The research log carries the affect module's goal, emotion and regulation fields
The curated research log SHALL record, from the affect module's real payloads, `affect.goal` with `action`, `id`, `drive`, `reason`, `priority` and `likelihood`; `affect.emotion` with `state`, `coping_available`, `obstruction`, `goal_significance_method` and `reappraised` besides its earlier fields; `affect.state` with `reset` and `alert`; and `affect.regulation` with `tier`, `action`, `intensity`, `episode_s`, `size`, `bias`, `decay_s`, `emotion_before` and `emotion_after`. The regulation payload's `source` SHALL be recorded as `target_source`, and the record's `source` SHALL stay the publishing module. A goal's `description` SHALL NOT be recorded.

#### Scenario: A goal end keeps its id, drive and reason
- **WHEN** the affect module publishes `affect.goal` with `action` `abandoned`, `id` `g1`, `description` `relieve boredom`, `drive` `boredom` and `reason` `stalled`
- **THEN** the research record has `action`, `id`, `drive` and `reason` with those values and no `description`

#### Scenario: A tier-1 regulation event is logged
- **WHEN** the affect module publishes `affect.regulation` with `tier` 1 and `source` `vision`
- **THEN** a research record is written with `tier` 1, `target_source` `vision` and `source` `affect`

### Requirement: The broadcast record carries the regulation bias and the feedback gains
The research log's `workspace.broadcast` record SHALL copy the metadata's `regulation_bias` as `source` and `factor`, and its `workspace_feedback` as `arm`, `gains` and, for each episode, `kind`, `conflicting`, `toward`, `away` and `delta`. It SHALL NOT copy the feedback's `sequence_prediction`.

#### Scenario: Feedback metadata without the sequence prediction
- **WHEN** a broadcast's metadata carries `workspace_feedback` with `gains`, one conflict episode and a 24-element `sequence_prediction`
- **THEN** the record's `workspace_feedback` has the gains and the episode and no `sequence_prediction`

### Requirement: The sleep record carries the link and node pruning counts
The research log's `sleep.sleep.completed` record SHALL keep `memory_links_pruned` and `memory_nodes_pruned`.

#### Scenario: Link counts survive
- **WHEN** a sleep completes with `memory_links_pruned` 3 and `memory_nodes_pruned` 1
- **THEN** the research record has both counts

### Requirement: Processor reports carry the change ratio
The research log SHALL keep `normalised_change` on `vision.report` and `audition.perception` when the payload carries it.

#### Scenario: The vision change ratio survives
- **WHEN** the vision module publishes `vision.report` with `normalised_change` 1.4
- **THEN** the research record has `normalised_change` 1.4
