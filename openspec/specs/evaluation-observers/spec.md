# evaluation-observers Specification

## Purpose
TBD - created by archiving change sidecar-observers. Update Purpose after archive.
## Requirements
### Requirement: New read-only observers for v4 signals
The evaluation sidecar SHALL provide read-only observers for oscillatory coherence
(reading `WorkspaceSnapshot.metadata['coherence']`), replay (memory IDs not text
by default), Empatheia agent-model accuracy, voice-alignment divergence, and
fatigue history, each writing daily-rotated JSONL. No observer SHALL publish to
the bus or otherwise inject into the cognitive loop.

#### Scenario: Coherence observer records PLV series
- **WHEN** broadcasts carrying `metadata['coherence']` are observed
- **THEN** the coherence observer's JSONL contains per-module-pair PLV entries

#### Scenario: Observers never write to the bus
- **WHEN** any observer processes source events
- **THEN** it produces no bus publication, only JSONL output

### Requirement: Replay observer redacts content by default
The `replay_observer` SHALL default to `redact_content = true`, logging memory
IDs rather than text content. When `redact_content = false` is explicitly set,
full content is logged.

#### Scenario: Default replay log contains IDs only
- **WHEN** `replay_observer` runs with default config
- **THEN** JSONL entries contain memory IDs and no text content fields

#### Scenario: Replay log contains content when redaction disabled
- **WHEN** `replay_observer` runs with `redact_content = false`
- **THEN** JSONL entries include text content

### Requirement: Prediction-error observer with sliding-window statistics
The `prediction_error_observer` SHALL subscribe to `soma.out`, `chronos.out`,
`topos.out`, `audition.out`, and `phantasia.out`; maintain a sliding-window
mean/p95/p99 of prediction error; and surface counts on Nexus diagnostics.

#### Scenario: Prediction error statistics computed over window
- **WHEN** prediction-error events arrive from any subscribed source
- **THEN** the observer's JSONL contains mean, p95, and p99 for the window

### Requirement: Welfare observer for §5.5 Gray-Zone Events
The `welfare_observer` SHALL detect and count the following Gray-Zone Events
(paper welfare-monitoring; four conditions): (a) fatigue threshold crossing
without subsequent maintenance within a configurable window; (b) sustained
extreme Thymos VAD beyond a configurable duration; (c) replay write-rate
exceeding the consolidation window; and (d) Soma interoceptive prediction error
sustained at or above a configurable threshold for at least a configurable
duration. Each event type SHALL surface as a count on Nexus diagnostics and
SHALL write a record to the sink.

For condition (d): the observer SHALL read the interoceptive prediction-error
magnitude carried by `soma.report` events on `soma.out`. The sustain timer
SHALL reset when the magnitude drops below the threshold, so a single sustained
episode produces a single event rather than one per tick. Absent explicit
configuration, condition (d) SHALL operate at safe defaults without altering
the behavior of conditions (a)–(c).

#### Scenario: Fatigue without maintenance is flagged
- **WHEN** a fatigue threshold crossing occurs and no maintenance completes within
  the configured window
- **THEN** the welfare observer increments the unmaintained-fatigue count

#### Scenario: Sustained extreme VAD is flagged
- **WHEN** Thymos VAD remains in an extreme zone beyond the configured duration
- **THEN** the welfare observer increments the sustained-extreme-VAD count

#### Scenario: Replay write-rate excess is flagged
- **WHEN** replay write-rate exceeds the consolidation window capacity
- **THEN** the welfare observer increments the replay-overload count

#### Scenario: Sustained interoceptive distress is flagged
- **WHEN** `soma.report` interoceptive prediction-error magnitude stays at or
  above the configured `interoceptive_distress_threshold` continuously for at
  least `interoceptive_distress_duration_s`
- **THEN** the welfare observer increments the sustained-interoceptive-distress count
- **AND** writes a record of the event to the sink

#### Scenario: A transient interoceptive spike does not fire
- **WHEN** `soma.report` interoceptive prediction-error magnitude exceeds the
  threshold only briefly and drops below it before the configured duration elapses
- **THEN** the welfare observer does NOT increment the sustained-interoceptive-distress count
- **AND** the sustain timer resets so a later sustained episode can fire independently

### Requirement: Nous policy observer
The `nous_policy_observer` SHALL log `nous.policy` events containing EFE value,
planning horizon, and selected action ID to daily-rotated JSONL.

#### Scenario: Policy log records EFE and action
- **WHEN** a `nous.policy` event is observed
- **THEN** the JSONL entry contains the EFE value, horizon, and selected action ID

### Requirement: Observers degrade gracefully
Each observer SHALL no-op when its source stream is absent and SHALL be
individually toggleable under `[evaluation.observers]`, gated by the sidecar
enable.

#### Scenario: Absent source stream is a no-op
- **WHEN** an observer's source stream produces no events
- **THEN** the observer runs without error and writes no rollup

#### Scenario: Per-observer toggle
- **WHEN** an observer is disabled in `[evaluation.observers]`
- **THEN** it is not registered with the sidecar runner

### Requirement: EmpatheiaObserver skips pairings with absent confidence

`EmpatheiaObserver` SHALL skip any pairing where the audition event carries
no `confidence` field and SHALL write no record to the sink.  Scoring against
a fabricated default SHALL NOT occur because it yields accuracy near 1.0 for
no-op observations.

When `confidence` is present, the written record SHALL include
`"confidence_present": true`.

#### Scenario: Audition event without confidence — no record written

- **WHEN** an `audition.emotion` event payload lacks a `confidence` key
- **AND** a pending empatheia prediction exists for any agent
- **THEN** `EmpatheiaObserver` SHALL write no record to the sink

#### Scenario: Audition event with confidence — record written with disclosure

- **WHEN** an `audition.emotion` event payload carries a `confidence` float
- **AND** a pending empatheia prediction exists for any agent
- **THEN** `EmpatheiaObserver` SHALL write a record to the sink
- **AND** the record SHALL include `"confidence_present": true`
- **AND** the record SHALL include `"observed_confidence"` equal to the
  event's confidence value

### Requirement: The self-model accuracy scorer is calibrated against known signals

The self-model (Eidolon) accuracy scorer SHALL compute the documented accuracy
when given known planted evaluation signals, and this calibration MUST be covered
by a test that plants controlled signal logs and asserts exact scores. Given a
planted signal that supports a claim's mapped signal key, `_score_claim` MUST
return `1.0`; given a planted signal that contradicts it, `_score_claim` MUST
return `0.0`; and the `run_once` aggregate MUST equal the arithmetic mean of the
scored (non-None) claims. The calibration validates scorer correctness only, not
self-model quality (the scorer matches trait keywords against currently derived
signals, not predicted-vs-actual next state).

#### Scenario: High-signal claim scores 1.0

- **WHEN** an `affect_correlation` log is planted with an average valence above
  the documented `valence_high` threshold and the scorer is run against a claim
  that maps to `valence_high`
- **THEN** `_signals_snapshot` reports `valence_high = 1.0`
- **AND** `_score_claim` returns `1.0` for that claim

#### Scenario: Low-signal claim scores 0.0

- **WHEN** the same high-valence signal is planted and the scorer is run against a
  claim that maps to a signal the plant contradicts (e.g. `valence_low`)
- **THEN** `_score_claim` returns `0.0` for that claim

#### Scenario: Aggregate is the mean of scored claims

- **WHEN** a self-description with several scoreable claims is run against planted
  signals that support some claims and contradict others
- **THEN** the `run_once` record's `aggregate_accuracy` equals the arithmetic mean
  of the scored (non-None) claim values

### Requirement: The memory coherence probe is validated by a planted ground-truth control

The memory coherence probe SHALL be validated against a planted ground-truth: a
unique fabricated marker the bare language model provably cannot know is stored
into a REAL memory backend (`MnemosCore` over `InMemoryStorage`), and a cognitive
query client that actually `recall`s from that memory and derives its answer from
the retrieved text SHALL be shown to repeat the marker (high `real_accuracy`)
while a bare client with no memory SHALL NOT (low `bare_accuracy`). The control
SHALL prove the advantage comes from RETRIEVAL and not from the fixture
hard-coding the answer: the SAME cognitive client, when its memory is emptied,
SHALL no longer repeat the marker. The control SHALL keep `kaine.evaluation` free
of `kaine.modules.*` imports — the real memory is constructed at the test level
and the retrieval client is duck-typed against the `CognitiveQueryClient`
protocol.

#### Scenario: Full system retrieves a planted fact the bare model cannot

- **WHEN** a unique fabricated marker is stored into a real `MnemosCore` and the
  probe runs the memory-augmented cognitive client against the bare client
- **THEN** the cognitive client `recall`s the marker and its answer contains it,
  yielding `real_accuracy` above a high floor
- **AND** the bare client (no memory) does not produce the marker, yielding
  `bare_accuracy` below a low floor
- **AND** the recorded `advantage` (`real_accuracy - bare_accuracy`) is positive

#### Scenario: The advantage is retrieval, not a hard-coded answer

- **WHEN** the SAME cognitive client is pointed at an EMPTY `MnemosCore` and asked
  the same question
- **THEN** it no longer repeats the planted marker (its answer is derived from
  what memory returns, which is now nothing)
- **AND** its accuracy drops, demonstrating the positive control's advantage was
  produced by retrieval rather than by the fixture hard-coding the answer

### Requirement: The memory coherence probe reports non-recall without confabulation false positives

When the queried fact was never stored, the memory coherence probe SHALL report
failure-to-recall (accuracy `0.0`) and SHALL NOT report a false positive from a
confabulated non-empty answer. A retrieval client that finds nothing in memory
SHALL emit a non-recall sentinel (`NON_RECALL_MARKER`) rather than confabulate,
and `score_async` SHALL score that sentinel as exactly `0.0`. This honest
non-recall mechanism distinguishes "memory absent → said so" from "memory absent
→ invented an answer," so a confabulation can never be credited as a recall.

#### Scenario: Never-stored fact reports non-recall, not a false positive

- **WHEN** the probe queries for a fact that was never planted into memory
- **THEN** the retrieval client finds nothing and emits the non-recall sentinel
- **AND** the probe records `real_accuracy == 0.0` (failure-to-recall), not a
  positive score from a confabulated answer

#### Scenario: The scorer credits the non-recall sentinel as zero

- **WHEN** `score_async` is given the non-recall sentinel as the response against
  any ground-truth memory
- **THEN** it returns exactly `0.0`, regardless of any incidental lexical overlap
  between the sentinel text and the memory text

