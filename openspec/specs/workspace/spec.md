# workspace Specification

## Purpose
This capability defines the workspace selection layer: it accepts a SalienceStrategy protocol, ships a v1 product-form implementation, selects a top-k coalition, and supports executive inhibition and novelty habituation for repeated payloads. Default settings let the cycle run without the affect module or goals, errors are tolerated, and placeholder factors are disclosed at runtime.

## Requirements

### Requirement: SalienceStrategy protocol with v1 product-form implementation
The workspace SHALL accept a salience strategy implementing
`async score(event, context) -> float`. The shipped v1 strategy
`RuleBasedSalience` SHALL compute the score as the product of four terms —
`intensity`, `novelty`, `goal_relevance`, `affect_modulation` — each in
the closed interval `[0.0, 1.0]`, with the final result clamped to the
same interval.

#### Scenario: Score equals the product of four terms
- **WHEN** intensity=0.8, novelty=0.5, goal_relevance=1.0, affect_modulation=1.0
- **THEN** `RuleBasedSalience.score(event, context)` returns 0.4

#### Scenario: Score clamps when any term is zero
- **WHEN** any of the four terms is 0.0
- **THEN** the returned score is 0.0

#### Scenario: Custom strategy substitutes cleanly
- **WHEN** the caller passes a custom `SalienceStrategy` that always returns 0.9
- **THEN** `Workspace.select` uses that strategy without modification

### Requirement: Top-k coalition selection
`Workspace.select` SHALL return a `WorkspaceSnapshot` whose
`selected_events` is the top `top_k` events by salience, ordered
descending. The default `top_k` SHALL be 5 and SHALL be configurable at
construction time and adjustable at runtime via `set_top_k`.

#### Scenario: Top-5 of ten events
- **WHEN** ten events are presented with distinct salience scores
- **THEN** the returned snapshot contains exactly five events in
  descending salience order

#### Scenario: Fewer events than k
- **WHEN** two events are presented with `top_k=5`
- **THEN** the snapshot contains both events without padding

### Requirement: Executive inhibition flag
`Workspace.select` SHALL set `WorkspaceSnapshot.inhibited` to `True`
when the top-1 salience score is strictly less than
`publication_threshold`, and `False` otherwise. The cycle continues to
broadcast inhibited snapshots; action modules SHALL check the flag.

#### Scenario: Top score below threshold inhibits
- **WHEN** the highest event score is 0.20 and `publication_threshold=0.35`
- **THEN** `snapshot.inhibited == True`

#### Scenario: Top score above threshold does not inhibit
- **WHEN** the highest event score is 0.50 and `publication_threshold=0.35`
- **THEN** `snapshot.inhibited == False`

#### Scenario: Empty event list returns an inhibited snapshot
- **WHEN** `select` is called with no events
- **THEN** `snapshot.selected_events == []` and
  `snapshot.inhibited == True`

### Requirement: Novelty habituates repeated payloads
`NoveltyTracker` SHALL return a novelty score in `[0.0, 1.0]` where 1.0
denotes "fingerprint never seen in window" and the score SHALL decrease
monotonically as the same fingerprint is observed within the window.
The window size SHALL be configurable.

#### Scenario: First observation is fully novel
- **WHEN** `observe(event)` is called once for an event the tracker has
  never seen
- **THEN** the returned novelty equals 1.0

#### Scenario: Repeated observation reduces novelty
- **WHEN** the same event is observed 10 times in a window of 32
- **THEN** the tenth observation's novelty is strictly less than the
  first

### Requirement: Defaults that let the system run without Affect and goals
`Workspace` SHALL accept `GoalScorer` and `AffectModulator` collaborators
with static defaults returning 1.0, so the product-form score works before
Phase 4 lands the real affect module and goal representation. The system SHALL
produce nonzero salience scores without either module present.

#### Scenario: Default scorer yields nonzero score
- **WHEN** `RuleBasedSalience` is constructed with the default static
  scorers and an event with intensity 0.6 and novelty 0.8 is scored
- **THEN** the returned score equals 0.48

### Requirement: Strategy error tolerance
The workspace SHALL tolerate `SalienceStrategy.score` exceptions by logging a
warning, recording that event's score as 0.0, and continuing to score the
remaining events on the same tick.

#### Scenario: One bad event does not crash the whole tick
- **WHEN** a strategy raises for one of three events presented to `select`
- **THEN** the returned snapshot contains the other two events ranked
  by their scores and the bad event has score 0.0 in
  `snapshot.salience_scores`

### Requirement: Placeholder salience factors are disclosed at runtime

`RuleBasedSalience` SHALL emit a one-time `log.warning` at construction when
the injected `goal_scorer` is a `StaticGoalScorer` or the `affect_modulator`
is a `StaticAffectModulator`, naming which factor(s) are bypassed and the
constant value returned. This makes the degraded two-factor salience mode
visible in operator logs without requiring source inspection.

`RuleBasedSalience` implements a four-factor product salience:
`intensity × novelty × goal_relevance × affect_modulation`. When either
factor is a static placeholder (returning a constant), the live salience is
effectively reduced to `intensity × novelty`. The scoring math is unchanged;
this requirement governs disclosure only.

#### Scenario: Static goal scorer warns at construction
- **WHEN** `RuleBasedSalience` is constructed with a `StaticGoalScorer`
- **THEN** a `WARNING`-level log message names `StaticGoalScorer` and the
  bypassed `goal_relevance` factor

#### Scenario: Static affect modulator warns at construction
- **WHEN** `RuleBasedSalience` is constructed with a `StaticAffectModulator`
- **THEN** a `WARNING`-level log message names `StaticAffectModulator` and the
  bypassed `affect_modulation` factor

#### Scenario: Real scorers emit no warning
- **WHEN** `RuleBasedSalience` is constructed with non-Static scorers
- **THEN** no warning is emitted

### Requirement: Drive-relevant sources are declared by the modules
The goal factor's drive-to-source mapping SHALL be built from what each registered module declares in `relieves_drives`, plus the declared workspace scaffolding sources. It SHALL be injected into the scorer, so the workspace layer never imports a module. Every declared tag SHALL be one of the four affect module's drives.

#### Scenario: A module's declaration drives the mapping
- **WHEN** a registered module declares `relieves_drives = {"curiosity"}`
- **THEN** with curiosity dominant, an event from that module is weighted as drive-relevant

#### Scenario: An unknown drive tag is rejected
- **WHEN** a module declares a tag that is not an affect module drive
- **THEN** building the mapping raises an error at boot

### Requirement: Arousal sharpens contrast above baseline
The v1 salience strategy SHALL score a candidate as the arousal level factor times a contrast function of its priority. The contrast function SHALL be the logistic function of slope `g` centred at one half, rescaled to map 0 to 0 and 1 to 1, and SHALL be the identity when `g` is zero. The slope SHALL be zero at or below baseline arousal and SHALL rise linearly to the configured contrast gain at full arousal.

#### Scenario: Identity at baseline arousal
- **WHEN** arousal is at its baseline
- **THEN** each score equals the level factor times the priority

#### Scenario: Contrast at full arousal
- **WHEN** arousal is 1.0 with the default contrast gain of 8
- **THEN** a priority of 0.8 maps to about 0.93 and a priority of 0.2 to about 0.07 before the level factor

### Requirement: Selection applies no per-source precision weight
The workspace's v1 salience strategy SHALL compute a candidate's priority as the clipped product of its intensity, novelty and goal relevance, with no weight that depends on the statistics of other events from its source. Precision enters through each processor's own scoring of its prediction error; arousal is the only global gain on the competition.

#### Scenario: A steady heartbeat does not suppress perceptual alerts
- **WHEN** one source publishes a constant intensity of 0.1 every second for ten minutes while another publishes alerts at 0.8 one time in ten, at baseline arousal
- **THEN** each alert's score equals the level factor at baseline arousal times 0.8, the same as when the steady source is absent

### Requirement: The workspace runs one arm of the planned ablation
The workspace SHALL run one of three arms, selected by `[workspace].arm`: `competitive` (the default), `matched` or `pooled` (paper §6.3, A.8). In the competitive arm selection, access and inhibition SHALL be as before. Every snapshot SHALL carry its arm in `metadata["arm"]`. The matched and pooled arms SHALL be refused when the coherence layer is on, and an unknown arm SHALL be refused. The `[workspace]` key guard SHALL accept `arm`, so the shipped configuration boots.

#### Scenario: The default arm is competitive
- **WHEN** the workspace is built without an arm
- **THEN** its snapshots equal those of the competitive arm and carry `metadata["arm"] == "competitive"`

#### Scenario: An unknown arm is refused
- **WHEN** the workspace is built with arm `"random"`
- **THEN** construction raises `ValueError`

### Requirement: The matched arm draws a score-blind coalition of the competitive size
In the matched arm, on a broadcast tick, the workspace SHALL score every candidate as in the competitive arm and SHALL draw `min(top_k, n)` of the `n` candidates uniformly without replacement, without regard to score, from a generator seeded from the run seed. The drawn members SHALL be ordered by score, descending. A drawn member SHALL be accessed when its score reaches the access threshold, and the snapshot SHALL be inhibited when no drawn member is accessed. The score table SHALL hold every candidate's score. A tick that is not a broadcast tick SHALL draw nothing, and a context that does not say whether the tick is a broadcast tick SHALL be refused rather than fall back to top-k selection. The generator's state SHALL NOT be persisted: the draws are reproducible within one uninterrupted run, and a restart or revive starts the stream again from the seed.

#### Scenario: The matched coalition has the competitive size
- **WHEN** a broadcast tick has 12 candidates and `top_k=5`
- **THEN** the matched coalition has 5 members, as the competitive coalition does

#### Scenario: The same seed reproduces the draws
- **WHEN** two matched runs with the same seed see the same broadcast ticks
- **THEN** they draw the same coalitions

#### Scenario: A matched selection without the broadcast flag is refused
- **WHEN** a matched `select` is called with a context that has no `is_experiential` key
- **THEN** it raises `ValueError`

#### Scenario: Access follows the threshold within the draw
- **WHEN** the best candidate scores 0.9, the threshold is 0.35, and every drawn member scores below 0.35
- **THEN** the snapshot is inhibited

### Requirement: The pooled arm broadcasts every candidate with no gate
In the pooled arm the workspace SHALL score no candidate. Every candidate of the tick SHALL be a member, in the tick's canonical order; the snapshot SHALL NOT be inhibited, even with no candidates; the score table SHALL carry each candidate's intensity in place of a score; and the metadata SHALL carry no access threshold.

#### Scenario: Every candidate is a member
- **WHEN** a pooled tick has 12 candidates and `top_k=5`
- **THEN** the snapshot has all 12 as members, is not inhibited, and scores each with its intensity

### Requirement: A pooled broadcast always replaces the context
A processor's broadcast context SHALL adopt every pooled broadcast with all its members, whatever their intensity, and an empty pooled broadcast SHALL replace the context with the featurization of the empty set. In the other arms a broadcast with no accessed member SHALL leave the context unchanged.

#### Scenario: A pooled member below the competitive threshold enters the context
- **WHEN** a pooled broadcast carries a member of intensity 0.1
- **THEN** that member's intensity enters the context

#### Scenario: An empty pooled broadcast replaces the context
- **WHEN** a processor holds a context and receives an empty pooled broadcast
- **THEN** its context becomes the featurization of the empty set

#### Scenario: The shipped configuration boots
- **WHEN** the shipped configuration with the `first_configuration` profile passes through the boot phase that builds the workspace
- **THEN** the key guard accepts `[workspace].arm` and the workspace runs the competitive arm

### Requirement: The score table has one key per candidate
Every candidate of a tick SHALL have an id unique within the tick's batch, and the cycle SHALL form it as `<stream>:<entry_id>` from the stream the candidate was read from and its bus entry id, because a bus entry id is unique only within its stream. The snapshot's `salience_scores` SHALL hold exactly one entry per candidate under that id, and each coalition member's id in `selected_events` and in the broadcast payload SHALL be the same id, in the competitive, matched and pooled arms and in both snapshots of the dual-path selection. The workspace SHALL refuse a candidate list in which two candidates share an id. A record written before this change keys its table by bare entry ids; a reader SHALL look up a member's score with the member's own id, which has the same form as the table's keys in the same record.

#### Scenario: Two streams publish the same entry id
- **WHEN** `interoception.out` and `vision.out` each hold an entry with id `1760000000000-0` and the cycle reads both on a broadcast tick
- **THEN** the broadcast's score table has two entries, `interoception.out:1760000000000-0` and `vision.out:1760000000000-0`, and each member's score under its own id is its own score

#### Scenario: Every arm keys members and scores alike
- **WHEN** a tick's candidates come from two streams that share an entry id, in the competitive, matched or pooled arm
- **THEN** the score table has one entry per candidate and every coalition member's id is a key of the table

#### Scenario: Duplicate candidate ids are refused
- **WHEN** `select` is given two candidates with the same id
- **THEN** it raises `ValueError`

#### Scenario: A bare legacy key is recognised
- **WHEN** `split_stream_entry_key` is given `1760000000000-0`
- **THEN** it returns `(None, "1760000000000-0")`

### Requirement: Tier-1 regulation bias on one source's scores
When `[workspace].regulation_bias` is true, the workspace SHALL read each tier-1 `affect.regulation` event among a tick's candidates and multiply the score `S'` of every candidate of the named source by `1 - b`, with `b = bias × exp(-(t - t1) / decay_s)` and `t1` the entity time the cycle collected the event, until a later tier-1 event replaces it. The factor SHALL lie in `[1 - bias, 1]`. Ticks with an active bias SHALL record `regulation_bias` (source and factor) in the broadcast metadata. With no tier-1 event, or with `regulation_bias` false, scores and metadata SHALL be bit-for-bit those without the layer. This is the only per-source factor affect applies to selection.

#### Scenario: The bias lowers the target and decays
- **WHEN** a tier-1 event names `vision` with bias 0.2 and decay 20 s
- **THEN** a vision candidate's score is multiplied by 0.8 on the next tick and by `1 - 0.2 e^-1` 20 entity seconds later, and other sources are unchanged

#### Scenario: No bias in the study arms
- **WHEN** any `config/studies/workspace_mediation_*.toml` is loaded
- **THEN** `[workspace].regulation_bias` is false, and a tick with a tier-1 event ranks candidates by `I × N` exactly as without it

### Requirement: Interest goal factor
With `[workspace].salience_goal_factor = "interest"`, the goal factor of a candidate from source `m` SHALL be `1 + gamma_I * D_I * lp+_m`. In it:
- `gamma_I` is `[workspace].interest_gain` (default 0.5, at least 0).
- `D_I` is the last-known curiosity value.
- `lp+_m` is `max(0, lp_m - lp_0) / (1 - lp_0)`, with `lp_m` the last-known `<m>_learning_progress` of `affect.state` and `lp_0` `[affect].learning_progress_floor`.
- `lp+_m` is 0 when the source has no finite learning progress.

The factor SHALL be exactly 1 when curiosity is 0 or unknown, and for any source without learning progress.

#### Scenario: No interest leaves selection unbiased
- **WHEN** curiosity is 0 and vision's learning progress is 0.9
- **THEN** a vision report's goal factor is exactly 1

#### Scenario: A non-perceptual source is never biased
- **WHEN** curiosity is 0.96 and vision's learning progress is 0.9
- **THEN** an `affect.drive` event's and a `sequence.report`'s goal factors are exactly 1

#### Scenario: The progressing source is raised
- **WHEN** curiosity is 0.96, vision's learning progress is 0.9, the floor is 0.05 and `gamma_I` is 0.5
- **THEN** a vision report's goal factor is `1 + 0.5 * 0.96 * (0.85 / 0.95)`

### Requirement: Only the priority is clipped
The salience score SHALL clip the priority `intensity * novelty * goal` to `[0, 1]` and SHALL NOT clip the goal factor above 1; a negative or non-finite goal factor SHALL count as 0. With the static or drive-relevance goal factor every score SHALL be unchanged.

#### Scenario: A raised factor saturates the priority
- **WHEN** an event of intensity 0.7 and novelty 1 has goal factor 1.5
- **THEN** its priority is 1

### Requirement: The interest factor keeps the affect snapshot live
When the interest goal factor is selected, the cycle SHALL refresh the affect state provider each tick. The provider SHALL fold each finite `<source>_learning_progress` term of the latest `affect.state`.

#### Scenario: Learning progress reaches the scorer
- **WHEN** an `affect.state` with `vision_learning_progress` 0.6 and curiosity 0.5 is observed
- **THEN** the interest scorer reads 0.6 for vision and 0.5 for curiosity

### Requirement: Predictive processors report graded intensity
The vision module, the audition module's acoustic path, the interoception module, the sequence module (once it has a temporal prediction error) and the audition module's neutral tone events SHALL report the module's alert intensity when the report meets the module's alert criterion, and otherwise `I_lo + (I_hi - I_lo) * min(1, r / 2)`, where `r` is the report's prediction error over the running mean of the module's recent errors, so the competition within a tick ranks graded surprise. Each such report's payload SHALL carry a boolean `alert`.

#### Scenario: Intensity rises with the error ratio
- **WHEN** a vision module report is not an alert and its error ratio is 1.0, with baseline 0.2 and alert level 0.7
- **THEN** its intensity is 0.45

#### Scenario: An alert takes the alert level
- **WHEN** a vision module report meets the alert criterion
- **THEN** its intensity is the alert level and its payload has `alert` true

### Requirement: Broadcasts carry the access threshold
Every broadcast SHALL record the access threshold in its metadata under `access_threshold`, so that a module can identify its accessed members: the coalition members whose score reaches the threshold. A broadcast is accessed when at least one member is.

#### Scenario: A rider below the threshold is not accessed
- **WHEN** a broadcast's coalition has members scoring 0.5 and 0.1 with an access threshold of 0.35
- **THEN** its metadata records the threshold 0.35, and only the member scoring 0.5 is accessed content

### Requirement: Processors hold the accessed broadcast as context
The context a processor holds SHALL be the featurization, weighted by intensity, of the accessed members of the latest accessed broadcast it has received, with the entity time elapsed since it received that broadcast. An inhibited broadcast SHALL leave the context unchanged, and before the first accessed broadcast there SHALL be no context.

#### Scenario: An inhibited broadcast does not replace the context
- **WHEN** a processor holds the context of an accessed broadcast and then receives an inhibited one
- **THEN** its context is unchanged apart from its age
