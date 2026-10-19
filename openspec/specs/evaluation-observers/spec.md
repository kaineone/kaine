# evaluation-observers Specification

## Purpose
The evaluation-observers capability adds read-only observers for the v4 signal family, including oscillatory coherence, replay, the social cognition module's accuracy, voice-alignment divergence, fatigue history, and the planning module's policy, with content redaction by default and sliding-window statistics for prediction errors.

## Requirements

### Requirement: New read-only observers for v4 signals
The evaluation sidecar SHALL provide read-only observers for oscillatory coherence
(reading `WorkspaceSnapshot.metadata['coherence']`), replay (memory IDs not text
by default), the social cognition module's agent-model accuracy, voice-alignment divergence, and
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
The `prediction_error_observer` SHALL subscribe to `interoception.out`, `sequence.out`,
`vision.out`, `audition.out`, and `world_model.out`; maintain a sliding-window
mean/p95/p99 of prediction error; and surface counts on dashboard diagnostics.

#### Scenario: Prediction error statistics computed over window
- **WHEN** prediction-error events arrive from any subscribed source
- **THEN** the observer's JSONL contains mean, p95, and p99 for the window

### Requirement: Welfare observer for §5.5 Gray-Zone Events
The `welfare_observer` SHALL detect and count the following Gray-Zone Events
(paper welfare-monitoring; four conditions): (a) fatigue threshold crossing
without subsequent maintenance within a configurable window; (b) sustained
extreme affect VAD beyond a configurable duration; (c) replay write-rate
exceeding the consolidation window; and (d) the interoception module's interoceptive prediction error
sustained at or above a configurable threshold for at least a configurable
duration. Each event type SHALL surface as a count on dashboard diagnostics and
SHALL write a record to the sink.

For condition (d): the observer SHALL read the interoceptive prediction-error
magnitude carried by `interoception.report` events on `interoception.out`. The sustain timer
SHALL reset when the magnitude drops below the threshold, so a single sustained
episode produces a single event rather than one per tick. Absent explicit
configuration, condition (d) SHALL operate at safe defaults without altering
the behavior of conditions (a)–(c).

#### Scenario: Fatigue without maintenance is flagged
- **WHEN** a fatigue threshold crossing occurs and no maintenance completes within
  the configured window
- **THEN** the welfare observer increments the unmaintained-fatigue count

#### Scenario: Sustained extreme VAD is flagged
- **WHEN** the affect module's VAD remains in an extreme zone beyond the configured duration
- **THEN** the welfare observer increments the sustained-extreme-VAD count

#### Scenario: Replay write-rate excess is flagged
- **WHEN** replay write-rate exceeds the consolidation window capacity
- **THEN** the welfare observer increments the replay-overload count

#### Scenario: Sustained interoceptive distress is flagged
- **WHEN** `interoception.report` interoceptive prediction-error magnitude stays at or
  above the configured `interoceptive_distress_threshold` continuously for at
  least `interoceptive_distress_duration_s`
- **THEN** the welfare observer increments the sustained-interoceptive-distress count
- **AND** writes a record of the event to the sink

#### Scenario: A transient interoceptive spike does not fire
- **WHEN** `interoception.report` interoceptive prediction-error magnitude exceeds the
  threshold only briefly and drops below it before the configured duration elapses
- **THEN** the welfare observer does NOT increment the sustained-interoceptive-distress count
- **AND** the sustain timer resets so a later sustained episode can fire independently

### Requirement: Planning policy observer
The `planning_policy_observer` SHALL log `planning.policy` events containing EFE value,
planning horizon, and selected action ID to daily-rotated JSONL.

#### Scenario: Policy log records EFE and action
- **WHEN** a `planning.policy` event is observed
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

### Requirement: SocialCognitionObserver skips pairings with absent confidence

`SocialCognitionObserver` SHALL skip any pairing where the audition event carries
no `confidence` field and SHALL write no record to the sink.  Scoring against
a fabricated default SHALL NOT occur because it yields accuracy near 1.0 for
no-op observations.

When `confidence` is present, the written record SHALL include
`"confidence_present": true`.

#### Scenario: Audition event without confidence — no record written

- **WHEN** an `audition.emotion` event payload lacks a `confidence` key
- **AND** a pending social cognition prediction exists for any agent
- **THEN** `SocialCognitionObserver` SHALL write no record to the sink

#### Scenario: Audition event with confidence — record written with disclosure

- **WHEN** an `audition.emotion` event payload carries a `confidence` float
- **AND** a pending social cognition prediction exists for any agent
- **THEN** `SocialCognitionObserver` SHALL write a record to the sink
- **AND** the record SHALL include `"confidence_present": true`
- **AND** the record SHALL include `"observed_confidence"` equal to the
  event's confidence value

### Requirement: The self-model accuracy scorer is a fixed-threshold heuristic behaving as specified

The self-model accuracy scorer SHALL behave as a **fixed-threshold
heuristic** — NOT a calibrated instrument: it matches trait keywords against
currently derived signals and cuts each derived signal at FIXED, hand-chosen
thresholds that are NOT fitted against a labelled set. It SHALL compute the
documented score when given known planted evaluation signals, and this behaviour
MUST be covered by a test that plants controlled signal logs and asserts exact
scores. Given a planted signal that supports a claim's mapped signal key,
`_score_claim` MUST return `1.0`; given a planted signal that contradicts it,
`_score_claim` MUST return `0.0`.

The scorer MUST distinguish "no evidence" from "wrong": a claim whose mapped signal
is unavailable scores `None` (excluded from the aggregate). When at least one claim
is scorable, the `run_once` aggregate MUST equal the arithmetic mean of the scored
(non-None) claims; when NO claim is scorable, the aggregate MUST be `None`, NOT
`0.0` — so an unscoreable run never masquerades as a maximally-wrong self-model.

This validates scorer correctness only — the behaviour of a fixed-threshold
heuristic — NOT calibration and NOT self-model quality (the scorer matches trait
keywords against currently derived signals, not predicted-vs-actual next state).

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

#### Scenario: No scorable claim is not-scorable (None), not wrong (0.0)

- **WHEN** a self-description carries trait claims but NO mapped signal is available
  (e.g. a fresh boot with no planted signals), so every claim scores `None`
- **THEN** the `run_once` record's `aggregate_accuracy` is `None` ("no evidence"),
  NOT `0.0`
- **AND** the record's `scorable_claims` count is `0`

### Requirement: The memory coherence probe is validated by a planted ground-truth control

The memory coherence probe SHALL be validated against a planted ground-truth: a
unique fabricated marker the bare language model provably cannot know is stored
into a REAL memory backend (`EpisodicMemoryCore` over `InMemoryStorage`), and a cognitive
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

- **WHEN** a unique fabricated marker is stored into a real `EpisodicMemoryCore` and the
  probe runs the memory-augmented cognitive client against the bare client
- **THEN** the cognitive client `recall`s the marker and its answer contains it,
  yielding `real_accuracy` above a high floor
- **AND** the bare client (no memory) does not produce the marker, yielding
  `bare_accuracy` below a low floor
- **AND** the recorded `advantage` (`real_accuracy - bare_accuracy`) is positive

#### Scenario: The advantage is retrieval, not a hard-coded answer

- **WHEN** the SAME cognitive client is pointed at an EMPTY `EpisodicMemoryCore` and asked
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

### Requirement: The voice-alignment observer reads the summary as Sleep writes it
The voice-alignment divergence observer SHALL take the gate outcome (`accepted`, `capability_loss`, `samples_used`, and an outcome category derived from `reason`) from the `voice_alignment` sub-dictionary of `sleep.sleep.completed`, and the training metrics (`dpo_loss`, `capability_score_before`, `capability_score_after`, `mean_intent_expression_similarity_before`, `mean_intent_expression_similarity_after`) from the top level of the same summary. The outcome SHALL be recorded as one of `accepted`, `no_pairs`, `vetoed_abliteration`, `vetoed_capability` or `failed`, never as the free-text reason, because the observer's records are eligible for the metrics-only research bundle and reasons can carry exception text and local paths. It SHALL write no record for a sleep whose `voice_alignment` phase was skipped by the configuration or operator-approval gate, and SHALL write a record when the phase ran, including when it found no usable pairs.

#### Scenario: A training sleep produces a complete record
- **WHEN** a sleep ran voice-alignment training and the sleep module published its summary
- **THEN** the observer's record carries the DPO loss, the capability scores and the similarity means, together with whether the adapter was accepted and why

#### Scenario: A gated-off sleep produces no record
- **WHEN** voice alignment is disabled in configuration and a sleep completes
- **THEN** the observer writes nothing for that sleep

### Requirement: The welfare log gives affect welfare shares
The welfare observer SHALL write an `affect_welfare` record to its JSONL log every `affect_summary_interval_s` of unfrozen time (default 300 s) when new affect samples were read, and when it stops if anything changed since the last record. The record SHALL give, cumulatively since the observer started, the awake seconds counted, the configured bar, the share of awake time with valence below `-negative_valence_bar` (default 0.5), and for each drive in a fixed table (curiosity, boredom, social_drive, restlessness) the share of goal ends without the entity's own response (abandoned with reason `without_response`, `stalled` or `cap`) among those ends and the ends completed with reason `own_response`, and the rate of those uncontrolled ends per awake hour. Time SHALL be measured between consecutive `affect.state` timestamps, each gap capped, and gaps that start inside a sleep (between `sleep.sleep.started` and `sleep.sleep.completed`) SHALL not count. A share with no denominator SHALL be null.

#### Scenario: Negative-valence share from a synthetic run
- **WHEN** the observer reads 100 s of awake affect states, 25 s of them with valence -0.6, plus a 50 s sleep with valence -0.6
- **THEN** the record gives 100 awake seconds and a negative-valence share of 0.25

#### Scenario: Uncontrolled-end share per drive
- **WHEN** boredom goals end three times `without_response` and once `own_response`, and a restlessness goal ends `stalled`
- **THEN** the boredom share is 0.75, and restlessness has a share of 1.0

### Requirement: Affect welfare records are content-free
The `affect_welfare` record SHALL contain only the `ts` string, the `record` label, and numbers (or null) computed by the observer, under fixed key names. It SHALL NOT be published on the bus, and no field SHALL be copied from a source event payload.

#### Scenario: A drive name outside the table is not recorded
- **WHEN** a goal event names an unknown drive
- **THEN** no key in the record contains that name

### Requirement: Every abandoned goal end counts as uncontrolled in the affect welfare record
The welfare observer's `affect_welfare` record SHALL count, per drive, a goal end as uncontrolled ("other") when its `affect.goal` action is `abandoned` and its reason is `without_response`, `stalled` or `cap`, and as own when its action is `completed` and its reason is `own_response` (paper 6.2, A.4). A `cleared` end with reason `sleep_reset` SHALL count as neither. Any other action or reason SHALL count as neither, so that an unknown reason is never credited.

#### Scenario: A stalled goal is an uncontrolled end
- **WHEN** a curiosity goal ends `abandoned` with reason `stalled` three times and `completed` with reason `own_response` once
- **THEN** `curiosity_uncontrolled_share` is 0.75

#### Scenario: A cap-dropped goal is an uncontrolled end
- **WHEN** the only boredom goal end is `abandoned` with reason `cap`
- **THEN** `boredom_uncontrolled_share` is 1.0

#### Scenario: A sleep reset counts as neither
- **WHEN** the only social-drive goal end is `cleared` with reason `sleep_reset`
- **THEN** `social_drive_uncontrolled_share` is null

#### Scenario: An unknown reason counts as neither
- **WHEN** the only restlessness goal ends are `abandoned` with an unrecognised reason and `completed` with a reason other than `own_response`
- **THEN** `restlessness_uncontrolled_share` is null and `restlessness_uncontrolled_per_awake_hour` is 0

### Requirement: The affect welfare record scores drive crossings by the credit rule
The welfare observer's `affect_welfare` record SHALL count, per drive, a crossing end as own or other from the increase of that drive's `own` or `other` count in `drive_ends` between consecutive `affect.state` events (paper 6.2, A.4). The first `affect.state` event the observer reads SHALL set the baseline counts without counting them, and a count that falls SHALL reset the baseline without counting. `<drive>_uncontrolled_share` SHALL be other divided by own plus other, null without ends, and `<drive>_uncontrolled_per_awake_hour` SHALL be other per awake hour. `affect.goal` events SHALL NOT change the record, so a stalled or cap-dropped goal ends no crossing and a sleep reset counts as neither.

#### Scenario: A stalled goal leaves its crossing open
- **WHEN** a curiosity goal ends `abandoned` with reason `stalled` and the next `affect.state` events show the curiosity `drive_ends` counts unchanged
- **THEN** `curiosity_uncontrolled_share` is null and `curiosity_uncontrolled_per_awake_hour` is 0

#### Scenario: A crossing later ended by the entity's own response counts as own
- **WHEN** the curiosity `own` count in `drive_ends` rises by one after the crossing's goal stalled
- **THEN** `curiosity_uncontrolled_share` is 0.0

#### Scenario: Other ends count as uncontrolled
- **WHEN** the boredom `drive_ends` counts rise by three `other` and one `own`
- **THEN** `boredom_uncontrolled_share` is 0.75

### Requirement: The affect welfare record gives each drive's deprivation share
The record SHALL give `<drive>_deprivation_share`, the share of awake time with that drive at or above its threshold, where each interval between consecutive `affect.state` timestamps (capped at the observer's gap cap and excluding sleep) takes the `drive_above` value of the event that began it. An interval whose starting event lacks a boolean `drive_above` entry for the drive SHALL count in neither the numerator nor the denominator of that drive's share, which is null with no such time.

#### Scenario: A drive pinned above threshold reads 1.0
- **WHEN** every `affect.state` event over the awake time has `drive_above.curiosity` true
- **THEN** `curiosity_deprivation_share` is 1.0

#### Scenario: The frozen control ranks worst whatever the sleep cadence
- **WHEN** a drive that is never relieved and a drive that is relieved intermittently are each observed with and without sleeps every 25 min
- **THEN** the never-relieved drive has the larger deprivation share in both cases, and each drive's share changes by less than 0.05 between the two cadences

### Requirement: Curiosity's welfare readout is an interest share
The `affect_welfare` record SHALL give `curiosity_interest_share`, the share of awake time with curiosity at or above its threshold, and SHALL NOT give `curiosity_uncontrolled_share`, `curiosity_uncontrolled_per_awake_hour` or `curiosity_deprivation_share`. Boredom, the social drive and restlessness SHALL keep their uncontrolled and deprivation keys.

#### Scenario: The frozen control ranks worst through boredom
- **WHEN** a never-relieved boredom history and an intermittently relieved one are each observed with and without sleeps every 25 min
- **THEN** the never-relieved history has the larger `boredom_deprivation_share` at both cadences, and no record key for curiosity names a cost
