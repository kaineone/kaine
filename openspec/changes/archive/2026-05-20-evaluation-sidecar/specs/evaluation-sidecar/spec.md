## ADDED Requirements

### Requirement: No core module depends on the sidecar
No file under `kaine/` outside `kaine/evaluation/` SHALL import
anything from `kaine.evaluation`. The sole exception SHALL be
`kaine/cycle/__main__.py`, which conditionally instantiates the
sidecar when `[evaluation].enabled` is true.

#### Scenario: grep proves the boundary
- **WHEN** `git grep "from kaine.evaluation" -- kaine/` is run
- **THEN** only `kaine/cycle/__main__.py` appears as a match

### Requirement: Sidecar is enabled by default but fully toggleable
The `[evaluation]` config block SHALL ship with `enabled = true`
and per-component flags all true. Setting `enabled = false` SHALL
skip sidecar boot entirely. Setting an individual per-component
flag false SHALL skip just that observer.

#### Scenario: Master switch off
- **WHEN** `[evaluation].enabled = false`
- **THEN** the cycle entrypoint does NOT construct any sidecar
  observer

#### Scenario: Per-component opt-out
- **WHEN** `[evaluation].enabled = true` and
  `[evaluation].ab_divergence = false`
- **THEN** the SidecarRegistry contains every observer except the
  A/B divergence observer

### Requirement: TrajectoryRecorder writes JSONL snapshots
The TrajectoryRecorder SHALL subscribe to `workspace.broadcast`
events and append one JSONL line per snapshot to a daily-rotated
file under the configured `trajectory_dir`. Each line SHALL include
`tick_index`, `timestamp`, `selected` events (full payload),
`salience_scores`, and the current Thymos state vector when
available.

#### Scenario: Snapshot written
- **WHEN** Syneidesis publishes a broadcast with tick_index=42
- **THEN** the trajectory file contains a JSONL line with
  tick_index=42 within the configured flush interval

### Requirement: TrajectoryRecorder rotates and retains
The TrajectoryRecorder SHALL roll over to a new file at UTC
midnight. Files older than `retention_days` SHALL be deleted on the
next sidecar startup or on the next rotation event.

#### Scenario: Retention purges
- **WHEN** the recorder starts with `retention_days = 30` and a
  31-day-old file exists in `trajectory_dir`
- **THEN** that file is removed

### Requirement: ABDivergenceObserver runs second inference and logs similarity
The ABDivergenceObserver SHALL subscribe to `lingua.external`
events, generate a "bare LLM" output using the same chat endpoint
with only the user input (no workspace context), compute cosine
similarity using a small embedder, and write the pair to
`data/evaluation/ab_divergence/<date>.jsonl`. The bare output text
SHALL NOT appear in any user-facing surface.

#### Scenario: Pair logged
- **WHEN** Lingua publishes an external_speech event with text
  "the answer is 42" and the user input was "what's the answer"
- **THEN** the ab_divergence log contains an entry with the real
  text, the bare-LLM text, and a `cosine_similarity` field in
  [0.0, 1.0]

#### Scenario: Sample rate honored
- **WHEN** `ab_sample_rate = 0.1` and 100 lingua.external events
  flow through
- **THEN** approximately 10 (with ±5 tolerance) entries appear in
  the ab_divergence log

### Requirement: VoiceTrackingObserver records Hypnos cycle stats
The VoiceTrackingObserver SHALL subscribe to `hypnos.out` events of
type `hypnos.cycle_complete` and write per-cycle summary lines
including `pairs_processed`, `pairs_above_threshold`, `dpo_loss`,
`adapter_accepted`, `mean_intent_expression_similarity_before`,
`mean_intent_expression_similarity_after`.

#### Scenario: Cycle complete summarised
- **WHEN** Hypnos publishes a cycle_complete event with payload
  carrying those stats
- **THEN** the voice_tracking log contains a matching entry

### Requirement: AttributionRecorder builds module histograms
The AttributionRecorder SHALL maintain a running histogram of
module sources that contributed to workspace broadcasts. It SHALL
flush per-hour rollups to `data/evaluation/attribution/<date>.jsonl`
and expose the running total in-memory for the Nexus tab.

#### Scenario: Attribution increments
- **WHEN** three workspace broadcasts arrive whose selected events
  are sourced from `{soma}`, `{soma, thymos}`, `{mnemos}`
- **THEN** the running histogram reads `soma: 2, thymos: 1,
  mnemos: 1`

### Requirement: AffectCorrelationRecorder pairs Thymos state with output
The AffectCorrelationRecorder SHALL log paired (Thymos state,
Lingua output characteristics) records for every external speech
event. Output characteristics include `length_chars`,
`length_tokens`, `lexical_diversity`, `hedge_word_count`,
`latency_ms`.

#### Scenario: Pair logged
- **WHEN** Lingua publishes an external_speech event with text
  "perhaps we should consider"
- **THEN** the affect_correlation log contains an entry with
  hedge_word_count > 0 and the current Thymos state vector

### Requirement: MemoryProbeRunner only counts out-of-context probes
The MemoryProbeRunner SHALL run on a configurable interval
(default 60 minutes) and SHALL emit a probe ONLY when the
reference episodic memory pre-dates the LLM's effective context
window. The runner's `count_probe` method SHALL return False for
in-context references; out-of-context probes SHALL be logged with
accuracy and bare-LLM-baseline result.

#### Scenario: In-context probe skipped
- **WHEN** the runner selects a memory with timestamp newer than
  `context_window_seconds_ago`
- **THEN** `count_probe` returns False and no log entry is written

### Requirement: ProactiveAuditObserver logs unprompted outputs
The ProactiveAuditObserver SHALL log every Lingua external speech
event whose causal chain does NOT include a recent user input.
Each log entry SHALL include `trigger_module`, `trigger_salience`,
`thymos_state`, and the workspace snapshot's tick_index.

#### Scenario: Proactive output captured
- **WHEN** Lingua publishes external_speech with no recent
  audio_in.transcription event in the causal chain
- **THEN** the proactive_audit log contains an entry with
  `trigger_module` matching the highest-salience event in the
  triggering snapshot

### Requirement: EidolonAccuracyRunner scores self-description daily
The EidolonAccuracyRunner SHALL run once per configurable interval
(default 24 hours), submit "describe yourself" through an internal
evaluation channel, parse the response for claim phrases (curious,
cautious, honest, etc.), and score each claim against the
evaluation logs. The aggregate score SHALL be appended to the
eidolon_accuracy log.

#### Scenario: Claim about curiosity verified
- **WHEN** KAINE's self-description includes "I'm curious" and the
  evaluation logs show the curiosity drive elevated > 0.5 in the
  last 24 hours
- **THEN** that claim scores 1.0; if curiosity was at baseline,
  the claim scores 0.0

### Requirement: SleepSnapshotRecorder captures paired before/after
The SleepSnapshotRecorder SHALL subscribe to `hypnos.began_rest`
and `hypnos.ended_rest`, fetch a state snapshot from Nous /
Mnemos / Thymos / Chronos / Voice via their published `*.serialize`
events or via the recorded module-serialize bus stream, and write a
paired before/after record.

#### Scenario: Pair written
- **WHEN** Hypnos publishes began_rest then ended_rest
- **THEN** the sleep_snapshots log contains a single record with
  `before` and `after` fields, both timestamped

### Requirement: AsyncJsonlSink is non-blocking
Every observer SHALL use the shared `AsyncJsonlSink` so the
sidecar never blocks the cognitive cycle. Writes go through an
`asyncio.Queue` and a background flush task batches them to disk.

#### Scenario: Backpressure does not block observer
- **WHEN** an observer writes 10000 entries faster than disk can
  absorb
- **THEN** writes return immediately and the queue grows; the
  observer is never blocked synchronously on disk I/O

### Requirement: Nexus diagnostics adds evaluation tab
The Nexus diagnostics surface SHALL include an `/evaluation`
sub-route that renders sidecar metrics: A/B divergence over time,
voice alignment over sleep cycles, module attribution histogram,
proactive output frequency, sleep before/after table, Eidolon
accuracy, affect-correlation matrix. The route SHALL NEVER expose
A/B bare-LLM text or any raw event payload text.

#### Scenario: Eval tab content-free
- **WHEN** an operator opens `/diagnostics/evaluation`
- **THEN** the rendered HTML contains no string from any A/B bare-
  LLM output and no message body text from any logged event
