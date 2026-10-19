# affect Specification

## Purpose
The affect module holds KAINE's affect. This capability covers its dimensional affect state and homeostatic drift, appraisal into categorical emotions, its four drives, the goal ledger and goal relevance, and the salience multiplier it gives the workspace.

## Requirements

### Requirement: Dimensional state with homeostatic drift
The affect module SHALL maintain a `DimensionalState` containing `valence`
(float in `[-1, 1]`), `arousal` (float in `[0, 1]`), and `dominance`
(float in `[-1, 1]`). On every internal tick arousal and dominance SHALL
drift toward their configured baselines by a configurable fraction
(`drift_rate_per_s`) of the elapsed subjective time, and valence SHALL
relax toward its target (see "Valence tracks the rate of change of
prediction error"), each clamped to the valid range for its dimension.
The configured baseline valence SHALL be the initial valence and the
valence after an affective reset.

#### Scenario: Drift moves valence toward baseline
- **WHEN** the state has `valence=0.8`, the baseline is 0.0, there is no
  learning progress, the interoception module's wellness is 0.5 and no perceived emotion is
  present (so the valence target equals the baseline), and 2.0 seconds pass
- **THEN** the new valence is between 0.0 and 0.8 (strictly less
  than the prior value)

#### Scenario: Drift moves arousal toward baseline
- **WHEN** the state has `arousal=0.8`, the baseline is 0.3, and
  `drift_rate_per_s=0.5` is applied for 2.0 seconds
- **THEN** the new arousal is between 0.3 and 0.8 (strictly less
  than the prior value)

#### Scenario: Clamping enforced on out-of-range inputs
- **WHEN** an update attempts to set `arousal=1.5`
- **THEN** the resulting state has `arousal == 1.0`

### Requirement: Scherer CPM five-check appraisal produces categorical emotions
The affect module SHALL run an appraisal sequence implementing Scherer's
Component Process Model: five callables in order (novelty,
intrinsic_pleasantness, goal_significance, coping_potential,
norm_compatibility), each returning a score in `[-1, 1]`. The
resulting 5-tuple SHALL be mapped to one of seven categorical
emotions via a pure function `classify(scores) -> CategoricalEmotion`:
`joy`, `sadness`, `anger`, `fear`, `surprise`, `disgust`, `neutral`.
Fear SHALL follow the fear profile of Sander, Grandjean and Scherer (2005, Table 3): `classify()` SHALL return `fear` only when coping is available, pleasantness is at or below -0.3, novelty is above 0.3 and coping is at or below -0.3, provided the near-neutral and surprise rules did not match first. The goal score SHALL NOT gate fear beyond the coping availability that needs a nonzero goal score, because Table 3's fear obstruction is anticipated and KAINE's obstruction term is retrospective.

#### Scenario: Positive pleasantness + positive goal yields joy
- **WHEN** `classify((novelty=0.2, pleasantness=0.7, goal=0.6,
  coping=0.5, norm=0.3))` is invoked
- **THEN** the returned emotion is `CategoricalEmotion.JOY`

#### Scenario: Negative pleasantness + negative coping yields fear
- **WHEN** `classify()` gets novelty 0.7, pleasantness -0.6, goal score -0.5 and coping -0.5 with coping available
- **THEN** the returned emotion is `CategoricalEmotion.FEAR`

#### Scenario: Near-neutral pleasantness does not yield fear
- **WHEN** `classify()` gets novelty 0.7, pleasantness -0.001, goal score -0.5 and coping -0.5 with coping available
- **THEN** the returned emotion is not `CategoricalEmotion.FEAR`

#### Scenario: Fear needs novel content
- **WHEN** `classify()` gets pleasantness -0.6, goal score -0.5 and coping -0.5 with coping available, and novelty 0.1
- **THEN** the returned emotion is not `CategoricalEmotion.FEAR`

#### Scenario: Fear is reachable at a positive goal score
- **WHEN** `classify()` gets novelty 0.7, pleasantness -0.6, goal score 0.5 and coping -0.5 with coping available
- **THEN** the returned emotion is `CategoricalEmotion.FEAR`

#### Scenario: Near-zero across the board yields neutral
- **WHEN** every score is within `±0.1` of zero
- **THEN** the returned emotion is `CategoricalEmotion.NEUTRAL`

### Requirement: Four drive states with build, threshold, and hysteresis
The affect module SHALL maintain four drive accumulators: `curiosity`,
`boredom`, `social_drive`, `restlessness`. Each SHALL be a float in
`[0, 1]`. Each `tick(dt, signals)` SHALL increment the drive by its
configured build rate (modulated by the relevant signal) and decay it
toward 0 by its decay rate. When a drive crosses its threshold,
The affect module SHALL publish a `affect.drive` event at alert salience. The
drive SHALL only re-fire after dropping below `threshold * 0.9`
(hysteresis) — no event storms from a value oscillating around the
threshold.

#### Scenario: Crossing threshold publishes one drive event
- **WHEN** curiosity's value rises from 0.5 to 0.75 in one tick and
  its threshold is 0.7
- **THEN** exactly one `affect.drive` event is published with
  `drive="curiosity"`

#### Scenario: Hysteresis prevents re-fire above threshold
- **WHEN** a drive that just fired is updated to a value still
  exceeding its threshold but it has not yet dropped below
  `threshold * 0.9` since the prior fire
- **THEN** no additional `affect.drive` event is published

### Requirement: Goal ledger supports add/complete/abandon and relevance scoring
The affect module SHALL expose a `GoalLedger` with `add(description, priority)`
returning a goal id, plus `complete(id)`, `abandon(id)`, and
`relevance(event) -> float`. Each lifecycle change SHALL publish a
`affect.goal` event. `relevance` SHALL return a float in `[0, 1]`
based on token overlap between active goal descriptions and the
event's source/type/payload string, weighted by goal priority.

#### Scenario: Add publishes a affect.goal event
- **WHEN** `ledger.add("explore the perimeter", priority=0.6)` is
  called
- **THEN** a `affect.goal` event is published with `action="added"`,
  the returned id, and the description

#### Scenario: Completed goals do not contribute to relevance
- **WHEN** a goal is completed and `relevance(event)` is called with
  an event that strongly overlaps that goal's description
- **THEN** the returned relevance does not include any contribution
  from the completed goal

### Requirement: AffectModulator exposes salience multiplier to Workspace
The affect module SHALL expose an instance implementing the workspace's existing
`AffectModulator` protocol (`async modulate(event) -> float in
[0, 1]`). The returned multiplier SHALL be a function of the current
dimensional state — at least, higher arousal SHALL produce a strictly
larger multiplier than lower arousal for the same event.

#### Scenario: Higher arousal yields larger multiplier
- **WHEN** `modulate(event)` is called once with `arousal=0.2` and
  again with `arousal=0.8`
- **THEN** the second call returns a strictly greater value

### Requirement: Affective reset entry point for Sleep
The affect module SHALL expose `async affective_reset()` that snaps the
dimensional state to its configured baseline and decays every drive
to zero in a single call. Phase 6 the sleep module calls this during sleep.

#### Scenario: Reset restores baseline and zeroes drives
- **WHEN** state is `valence=0.7, arousal=0.8` and a drive is at 0.9,
  and `affective_reset()` is awaited
- **THEN** the state equals the configured baseline and every drive
  is 0.0

### Requirement: Default Affect config and disabled-by-default
The repository SHALL ship a `[affect]` block in `config/kaine.toml`
with default values for `baseline_valence`, `baseline_arousal`,
`baseline_dominance`, `drift_rate_per_s`, per-drive build/decay/
thresholds, appraisal weights, `publish_interval_s`,
`baseline_salience`, and `alert_salience`. `[modules].affect = false`
SHALL keep first boot from auto-registering the affect module.

#### Scenario: kaine.toml carries defaults
- **WHEN** an operator inspects `config/kaine.toml`
- **THEN** they find a `[affect]` section with the documented keys
  and `[modules].affect == false`

### Requirement: affect.emotion event discloses unavailable appraisal dimensions

The `affect.emotion` event payload SHALL carry `"norm_compatibility_available": false` while KAINE holds no standards to check content against. The models reviewed take standards as authored input, so the norm check stays undefined until an operator writes a list. No categorical rule SHALL require a norm score.

#### Scenario: norm_compatibility not wired

- **WHEN** a `affect.emotion` event is published
- **AND** no standards list exists
- **THEN** the payload carries `"norm_compatibility_available": false`
- **AND** downstream consumers MUST NOT interpret the numeric norm value as a real measurement

### Requirement: affect.emotion event discloses goal_significance method

The `affect.emotion` event payload SHALL carry `goal_significance_method`, naming how the published `goal_significance` score was computed: `"drive_relevance_v1"` when it was scored against the entity's dominant drive, `"drive_relevance_v1+token_overlap_v1"` when active ledger goals also contributed, `"token_overlap_v1"` when no drive-to-source table was injected and active ledger goals were scored, and `"unavailable"` when neither source exists, in which case the score SHALL be `0.0`.

#### Scenario: goal_significance is a proxy

- **WHEN** a `affect.emotion` event is published by the affect module assembled into the cycle with no active goals
- **THEN** the payload carries `"goal_significance_method": "drive_relevance_v1"`

#### Scenario: No table

- **WHEN** a `affect.emotion` event is published by the affect module that was given no drive-to-source table and holds no active goals
- **THEN** the payload carries `"goal_significance_method": "unavailable"` and `goal_significance` is `0.0`

### Requirement: GoalLedger.relevance returns zero with no active goals

`GoalLedger.relevance()` SHALL return `0.0` when no active goals are
registered, preventing spurious small positive values from acting as
goal-significance noise in the appraisal.

#### Scenario: no active goals

- **WHEN** `GoalLedger.relevance()` is called and no goals are in the ACTIVE state
- **THEN** the return value is `0.0`

---

### Requirement: PassiveDecay regulation is visible in traces

`PassiveDecay.suggest()` SHALL emit a one-time `log.debug` message on its
first call so that the absence of an active regulation policy is visible in
traces rather than silently doing nothing every tick.

#### Scenario: first use of PassiveDecay

- **WHEN** `PassiveDecay.suggest()` is called for the first time
- **THEN** a debug log message is emitted naming the passive policy
- **AND** subsequent calls do not repeat the message

### Requirement: Goals survive preservation
The affect module SHALL include its goal ledger in its serialized state — each goal's id, description, priority, state, and created and completed times — and SHALL restore it on deserialize, so a revived entity holds the goals it held when preserved. A restore SHALL NOT publish goal lifecycle events. Invalid goal entries SHALL be dropped with a log, and the rest SHALL load.

#### Scenario: Goals round-trip
- **WHEN** the affect module holds an active, a completed and an abandoned goal and is serialized and restored into a fresh affect module
- **THEN** the restored ledger holds the same three goals with the same ids, states and priorities, and relevance scoring counts only the active one

#### Scenario: A snapshot without goals
- **WHEN** the affect module is restored from a snapshot that has no goals key
- **THEN** its goal ledger is left as it was

### Requirement: The modulator reports a contrast gain
The affect module's state modulator SHALL report a contrast gain that is zero when arousal is at or below the baseline arousal and rises linearly to the configured `arousal_contrast_gain` at arousal 1.0. A static modulator SHALL report zero.

#### Scenario: No contrast at baseline
- **WHEN** arousal equals the baseline arousal
- **THEN** the contrast gain is 0.0

### Requirement: Affect publishes its state on a timer
The affect module SHALL update its state and publish `affect.state` every `publish_interval_s` of subjective time whether or not a workspace broadcast arrives.

#### Scenario: State without broadcasts
- **WHEN** the affect module runs for three publish intervals with no workspace broadcast
- **THEN** it publishes at least two `affect.state` events

### Requirement: Drives are setpoint deficits with relief
Each affect module drive SHALL evolve between events by the exact solution of linear build and decay toward the equilibrium `beta u / (beta u + delta)`, with build signal `u` in `[0, 1]`. Curiosity and boredom SHALL be relieved continuously, `D <- D exp(-rho c dt)`, so their relief does not depend on the perceptual report rate: curiosity with `c` the perceptual learning progress above a noise floor, boredom with `c` the excess of the fast perceptual alert rate over its slow, habituated rate beyond a margin. The social drive SHALL be relieved by a new operator interaction and restlessness by each action selection module intent other than REST, each as `D <- D (1 - rho c)`. Here `rho` is the drive's relief gain. With the shipped rates, the full-deprivation equilibrium `beta / (beta + delta)` of every drive SHALL exceed its threshold.

#### Scenario: Curiosity falls when perception is learning
- **WHEN** the perceptual modules' raw prediction errors fall steadily over a minute of subjective time
- **THEN** curiosity decreases

#### Scenario: Drives build under stationary noise
- **WHEN** a perceptual stream with noisy but stationary errors and a steady base rate of alerts runs for ten minutes of subjective time
- **THEN** curiosity and boredom both cross their thresholds

#### Scenario: Relief does not depend on the report rate
- **WHEN** the same time course of falling errors arrives at 10 reports per second and, separately, at 5
- **THEN** curiosity ends within 0.05 in both runs

#### Scenario: Drives stay bounded
- **WHEN** a drive's build signal is 1 for an hour of subjective time with no relief
- **THEN** its value stays at or below `beta / (beta + delta)`

### Requirement: Valence tracks the rate of change of prediction error
The affect module SHALL move valence toward `clip(P + (W - 0.5), -1, 1)` with time constant `valence_time_constant_s`, where `P` is the appraisal's intrinsic-pleasantness check, `clip(tanh(valence_progress_gain * g) + c, -1, 1)`, `g` the signed perceptual learning progress from time-decayed means of raw prediction error over subjective time, `c` the appraisal contribution of a perceived speaker emotion, and `W` the interoception module's last wellness. A module's means SHALL count only samples from its first positive error on, and SHALL be unbiased by any single sample: early on both equal the plain mean of the samples so far.

#### Scenario: Errors falling is pleasant
- **WHEN** the perceptual modules' raw prediction errors fall steadily on a healthy host
- **THEN** valence becomes positive

#### Scenario: A first-frame zero error does not depress valence
- **WHEN** a perceptual module reports a prediction error of 0 on its first frame and positive errors afterwards
- **THEN** the learning progress is computed from the first positive error, not from 0

#### Scenario: A low first sample does not depress valence
- **WHEN** a module's first positive error is well below its steady error
- **THEN** valence stays above -0.2 while the averages fill

### Requirement: Appraisal novelty reflects surprise
The affect module SHALL compute the novelty appraisal check as `1 - prod (1 - s_m)` over coalition members that carry a normalised error ratio `r`, with `s = clip(ln r / ln 3, 0, 1)`.

#### Scenario: Surprise is reachable
- **WHEN** the coalition holds a perceptual report with normalised error ratio 3 and pleasantness and goal significance are near zero
- **THEN** the categorical emotion is SURPRISE

### Requirement: Sleep's affective reset starts affect afresh
`affective_reset()` SHALL also clear the per-source learning-progress error means, the perceptual alert-rate averages, the intent rate and its counter, and any perceived speaker emotion, so that affect after sleep is computed from what happens after sleep. It SHALL keep the interoception module's last wellness reading and the interaction history.

#### Scenario: Valence does not rebound from pre-sleep progress
- **WHEN** perceptual errors have fallen steadily for two minutes, `affective_reset()` is awaited, and the affect module then updates for 30 s of entity time with no perceptual reports
- **THEN** valence stays within 0.1 of its baseline

### Requirement: A malformed peer event does not stop the peer consumer
When handling one event from a peer stream raises an exception, the affect module SHALL log it and continue with the next event.

#### Scenario: A bad event is skipped
- **WHEN** a peer event whose handling raises is followed by a valid perceptual report
- **THEN** the valid report is handled

### Requirement: Familiarity reaches the coupling weight
The affect module SHALL find the familiarity the social cognition module reports for the agent behind a perceived emotion: when an `social_cognition.agent_model` event carries a `source_label`, the affect module SHALL cache its familiarity under that label, which is the key it reads when it weights a perceived emotion from that channel.

#### Scenario: A familiar speaker raises the coupling weight
- **WHEN** the social cognition module publishes `social_cognition.agent_model` with `source_label` "live_mic" and familiarity 0.65, and the affect module then records a perceived emotion from "live_mic"
- **THEN** the familiarity the affect module uses for that emotion is 0.65

### Requirement: Retired Affect keys are ignored with a warning
The affect module factory SHALL accept `[affect].social_drive_time_scale_s` and
`[affect.coupling].coupling_max_rate_per_s`, retired keys that no longer drive
anything, SHALL NOT pass them to the affect module, and SHALL log a warning for each one
present that names the key and says it is ignored. The social drive SHALL build
at its configured build rate once an interaction has occurred, with no separate
time scale. Any other key outside the factory's accepted set SHALL still stop
boot.

#### Scenario: An old operator file still boots
- **WHEN** the operator configuration sets
  `[affect].social_drive_time_scale_s = 600.0`
- **THEN** the factory builds the affect module and logs a warning naming
  `[affect].social_drive_time_scale_s`

#### Scenario: The legacy coupling key warns too
- **WHEN** the operator configuration sets
  `[affect.coupling].coupling_max_rate_per_s = 0.3`
- **THEN** the factory builds the affect module and logs a warning naming
  `[affect.coupling].coupling_max_rate_per_s`

#### Scenario: Affect takes no social time scale
- **WHEN** the affect module's constructor's parameters are inspected
- **THEN** `social_drive_time_scale_s` is not among them

### Requirement: Coping potential is gated by relevance and estimated as a success ratio
The affect module SHALL compute coping potential only when the goal score is nonzero. When the goal score is 0, coping SHALL be unavailable: the appraisal scores SHALL carry `coping_available = False` with a numeric coping value of 0.0, and `classify()` SHALL NOT return fear, anger or sadness. When coping is available it SHALL be `2p - 1` with `p = (s + 1) / (s + f + 2)`. When the drive term sets the conducive part of the goal score (including a tie with the ledger term), `s` SHALL be the dominant drive's crossings ended by the entity's own response and `f` those ended any other way; when the ledger term sets it, `s` and `f` SHALL be the ledger's completed and abandoned goals. A crossing ends when the drive falls below its re-arm band. It SHALL count as own when the fall happens in a relief whose source is the entity's own response (learning progress for curiosity, intents for restlessness), or in `tick` when the entity's response held the build input below its no-response value and a counterfactual step at that value would not have fallen below the band. Every other end SHALL count as other, and a sleep reset SHALL count as neither. Arousal and valence SHALL NOT enter coping. The drive counts SHALL survive serialize and deserialize. The `affect.emotion` payload SHALL carry `coping_available`.

#### Scenario: Irrelevant content leaves coping unavailable
- **WHEN** the goal score is 0.0, pleasantness is -0.6 and novelty is 0.1
- **THEN** `coping_available` is false and the categorical emotion is neither `fear`, `anger` nor `sadness`

#### Scenario: No history gives neutral coping
- **WHEN** the dominant drive sets a goal score above 0 and has no ended crossings
- **THEN** coping is 0.0

#### Scenario: Crossings ended without the entity's response lower coping
- **WHEN** the dominant drive sets the goal score and two of its crossings ended other ways and none by its own response
- **THEN** coping is -0.5

#### Scenario: Crossings ended by the entity's response raise coping
- **WHEN** the dominant drive sets the goal score and two of its crossings ended by its own response and none other ways
- **THEN** coping is 0.5

#### Scenario: The ledger supplies power when it sets the score
- **WHEN** the ledger term exceeds the drive term and the ledger holds one completed and three abandoned goals
- **THEN** coping is 2 × (2 / 6) - 1

#### Scenario: Arousal does not move coping
- **WHEN** arousal changes and the drive and ledger counts do not
- **THEN** coping is unchanged

#### Scenario: Counts survive preservation
- **WHEN** the affect module is serialized and a new instance deserializes the state
- **THEN** every drive's own and other counts are restored

#### Scenario: External relief counts as failure
- **WHEN** a fired boredom drive falls below its re-arm band through novelty relief, or a fired social drive through another's voice
- **THEN** its other count rises and its own count does not

#### Scenario: A held-down build input counts as the response
- **WHEN** a fired curiosity drive falls below its re-arm band during `tick` with learning progress above 0, and the same step at zero learning progress would have left it above the band
- **THEN** its own count rises

#### Scenario: A negative goal score makes coping available
- **WHEN** the conducive part is 0 and the obstruction is 0.2
- **THEN** the goal score is -0.2 and `coping_available` is true

### Requirement: Disgust follows the Table 3 appraisal profile
`classify()` SHALL return `disgust` when intrinsic pleasantness is at or below -0.5, novelty is above 0.3 and the absolute goal score is below 0.3, whatever the norm compatibility score, provided the near-neutral, surprise, fear and anger rules did not match first. Novelty stands for Table 3's familiarity check: KAINE's single novelty check covers suddenness, familiarity and predictability, so low familiarity maps to high novelty. Norm compatibility SHALL stay unavailable: the module SHALL keep its numeric value at 0.0 and publish `norm_compatibility_available: false`.

#### Scenario: The Table 3 profile with no norm signal yields disgust
- **WHEN** `classify()` gets novelty 0.7, pleasantness -0.7, goal score 0.0, coping 0.0, norm 0.0 and `coping_available` false
- **THEN** the returned emotion is `disgust`

#### Scenario: A norm violation alone does not yield disgust
- **WHEN** `classify()` gets novelty 0.0, pleasantness -0.7 and norm -0.6, with every other score 0.0
- **THEN** the returned emotion is not `disgust`

#### Scenario: Relevant content does not yield disgust
- **WHEN** `classify()` gets novelty 0.7, pleasantness -0.7 and goal score 0.5, with coping 0.0
- **THEN** the returned emotion is not `disgust`

#### Scenario: Fear keeps precedence when coping is low
- **WHEN** `classify()` gets novelty 0.7, pleasantness -0.6, goal score 0.2 and coping -0.5 with coping available
- **THEN** the returned emotion is `fear`

### Requirement: Three-tier emotion regulation escalates on the A.5 rule
With `[affect.regulation].policy = "three_tier"` the affect module SHALL compute at every update the intensity `max(|v|, a - a0)` and SHALL treat the appraisal as negative when the last appraisal's pleasantness or goal score is below 0. An episode SHALL run from the first update with intensity at or above `set_point` and a negative appraisal to the first update without both. After `Δst` entity seconds of an episode, each increase of `floor(Δst / sustain_window_s) >= 1` SHALL fire one activation of tier `min(floor(Δst / sustain_window_s), 3)`. Every activation SHALL publish `affect.regulation` with `tier`, `action`, `intensity`, `episode_s` and `size`.

#### Scenario: Below the set point nothing fires
- **WHEN** intensity stays below `set_point` with a negative appraisal for 120 entity seconds
- **THEN** no `affect.regulation` event is published and the state equals that of the passive policy

#### Scenario: A non-negative appraisal fires nothing
- **WHEN** intensity stays at 0.8 for 120 entity seconds with pleasantness and goal score at or above 0
- **THEN** no `affect.regulation` event is published

#### Scenario: Sustained negative intensity escalates
- **WHEN** intensity stays at 0.8 with pleasantness -0.4 for 95 entity seconds with `sustain_window_s` 30
- **THEN** tiers 1, 2 and 3 fire once each, in that order, at 30, 60 and 90 seconds

### Requirement: Tier 1 targets the source with the largest negative intensity mass
During an episode the module SHALL sum, per source, the intensity of the members of each coalition appraised as negative. Tier 1 SHALL publish `action: "attentional_deployment"` with the source of largest mass (ties to the alphabetically first), `bias` equal to `selection_bias` and `decay_s` equal to `bias_decay_s`, and `size` equal to the bias; with no such member it SHALL publish no source and `size` 0.

#### Scenario: The dominant negative source is targeted
- **WHEN** an episode's negatively appraised coalitions hold vision members of total intensity 1.2 and audition members of total intensity 0.5
- **THEN** tier 1 names `vision` with bias 0.2

### Requirement: Tier 2 reappraises once per episode
Tier 2 SHALL re-run the appraisal of the last broadcast against the current coping and goal state at most once per episode and replace the categorical emotion with the classification of the result. When the emotion changes it SHALL publish `affect.emotion` with `reappraised: true`. It SHALL NOT change valence, arousal or dominance. Its event SHALL carry `emotion_before` and `emotion_after`, and `size` 1 if the emotion changed, else 0.

#### Scenario: Improved coping turns fear into another emotion
- **WHEN** a broadcast was appraised as fear with coping -0.8 and the dominant drive's success record has since raised coping to 0.8
- **THEN** tier 2 replaces fear with a non-fear emotion, publishes `affect.emotion` with `reappraised: true`, has `size` 1, and leaves valence unchanged

#### Scenario: Unchanged appraisal keeps the emotion
- **WHEN** tier 2 re-runs an appraisal whose coping and goal state have not changed
- **THEN** the emotion is kept, no `affect.emotion` event is published and `size` is 0

### Requirement: Tier 3 requests sleep through the maintenance path
Tier 3 SHALL publish `action: "request_maintenance"`, and the sleep module SHALL start a maintenance sleep on it under the same guards as the interoception module's request.

#### Scenario: A tier-3 request starts a sleep
- **WHEN** the sleep module, with fatigue-triggered maintenance on, reads an `affect.regulation` event with `action: "request_maintenance"` while not sleeping
- **THEN** it starts a sleep

### Requirement: Regulation is off during the developmental phase
The affect module SHALL fire no regulation activation while the injected developmental probe returns true, and SHALL end any episode then; with no probe, regulation SHALL run.

#### Scenario: No activation before maturation
- **WHEN** the probe returns true and intensity stays at 0.8 with a negative appraisal for 120 entity seconds
- **THEN** no `affect.regulation` event is published

#### Scenario: Tier 1 first after maturation
- **WHEN** the probe turns false and the condition then holds for 30 entity seconds
- **THEN** tier 1 fires

### Requirement: The passive policy is the off arm
With `policy = "passive"` the affect module SHALL behave exactly as before this change: no `affect.regulation` events, a zero adjustment, the same state and events.

#### Scenario: Passive matches the previous build
- **WHEN** the same inputs drive a passive module
- **THEN** its published events and state equal those of the previous build's module

### Requirement: Perceptual alerts raise arousal by the larger excess of the error and change ratios
On each `vision.report` or `audition.perception` event whose `alert` is true, the affect module SHALL raise arousal by `gamma_a * min(nu_cap, max(0, max(r_err, r_chg) - 1))`, with `gamma_a = 0.15`, `nu_cap = 4.0`, `r_err` the payload's `normalised_error` and `r_chg` its `normalised_change` (paper A.5 item 1). A ratio that is missing, not a number, or not finite SHALL be read as 0.0. An event whose `alert` is not true SHALL NOT raise arousal through this rule.

#### Scenario: A change alert raises arousal
- **WHEN** an alert report carries `normalised_error` 0.99 and `normalised_change` 3.0
- **THEN** arousal rises by 0.15 x 2.0

#### Scenario: An error alert is unchanged
- **WHEN** an alert report carries `normalised_error` 3.0 and `normalised_change` 0.5
- **THEN** arousal rises by 0.15 x 2.0, as before this change

#### Scenario: Both ratios present takes the larger
- **WHEN** an alert report carries `normalised_error` 2.0 and `normalised_change` 3.5
- **THEN** arousal rises by 0.15 x 2.5

#### Scenario: A report without the change ratio behaves as before
- **WHEN** an alert report carries `normalised_error` 2.5 and no `normalised_change`
- **THEN** arousal rises by 0.15 x 1.5

#### Scenario: A non-finite change ratio is ignored
- **WHEN** an alert report carries `normalised_error` 0.99 and a non-finite `normalised_change`
- **THEN** arousal does not change

#### Scenario: Non-alert reports never arouse
- **WHEN** a report with `alert` false carries `normalised_change` 5.0 and `normalised_error` 5.0
- **THEN** arousal does not change

### Requirement: The affective reset reports each goal it clears
`affective_reset()` SHALL remove every active goal and SHALL publish, for each removed goal, one `affect.goal` event whose payload carries `action: "cleared"`, `reason: "sleep_reset"`, and the goal's `id`, `description` and `drive`. A cleared goal SHALL count as neither completed nor abandoned: the ledger's outcome counts SHALL be unchanged by the reset.

#### Scenario: Two active goals are cleared by sleep
- **WHEN** the curiosity and restlessness drives have active goals and `affective_reset()` is awaited
- **THEN** two `affect.goal` events with action `cleared` and reason `sleep_reset` are published, one per goal id, each with that goal's drive
- **AND** no active goal remains and `outcome_counts()` is the same as before the reset

#### Scenario: A reset with no active goals publishes no goal event
- **WHEN** no goal is active and `affective_reset()` is awaited
- **THEN** no `affect.goal` event is published

### Requirement: The drive crossing latch survives a restore
`Affect.serialize()` SHALL store each drive's crossing latch under `drive_fired` as a map from drive name to boolean, and `deserialize()` SHALL restore it, so a drive that had fired before preservation does not fire again after a revive until it has fallen below its re-arm band. When the restored state has no boolean latch for a drive, `deserialize()` SHALL set the latch to true when the restored value is at or above the drive's threshold and to false otherwise.

#### Scenario: A fired drive does not re-fire after a round trip
- **WHEN** curiosity has crossed its threshold and fired, the module is serialized, and a new module deserializes the state and ticks with curiosity still above its threshold
- **THEN** no `affect.drive` crossing is published and no new goal is created

#### Scenario: State without latches infers them from the value
- **WHEN** the restored state has drive values but no `drive_fired` key, with curiosity at 0.9 and boredom at 0.5 against thresholds of 0.7
- **THEN** curiosity's latch is set and boredom's is not

### Requirement: The running affect estimates survive a restore
`Affect.serialize()` SHALL store the perceptual alert rates under `alert_rates` (`fast` and `slow`, in alerts per entity second), the per-source learning-progress error means under `error_means` (for each source its fast and slow time-decayed sums and counts), the intent rate under `intent_rate`, the last wellness under `wellness` and whether an interaction has been seen under `interaction_seen`. `deserialize()` SHALL restore each value that is present, finite and in range, SHALL take the restore time as each restored source's latest report time, and SHALL keep the constructor default for a missing or invalid value. No timestamp SHALL be stored.

#### Scenario: The alert rates and error means round-trip
- **WHEN** a module has received perceptual reports and alerts, is serialized, and a new module deserializes the state
- **THEN** the new module's alert rates, error means, intent rate, wellness and interaction flag equal the first module's
- **AND** its learning progress and alert excess on the next update at the same entity time equal the first module's

#### Scenario: A restore does not relieve boredom
- **WHEN** a module has settled on a steady base rate of alerts with boredom above its threshold and an active boredom goal, is serialized and restored, and the same base-rate alerts continue
- **THEN** the alert excess stays at 0, boredom is not relieved by them, and the boredom goal is not abandoned

#### Scenario: Older state still restores
- **WHEN** the restored state has none of the new keys, or has non-numeric or negative values for them
- **THEN** `deserialize()` raises nothing, the other saved fields are restored, and the missing or invalid estimates keep their constructor defaults

### Requirement: Perceptual arousal habituates to the base alert rate
On each `vision.report` or `audition.perception` event whose `alert` is true, the affect module SHALL raise arousal by `gamma_a * h * min(nu_cap, max(0, max(r_err, r_chg) - 1))`, where `h = max(clip_[0,1](r_f / max(r_s, r_0) - 1), exp(-r_s * tau_s))` is computed from the perceptual alert rates before this alert adds `1/tau_f` and `1/tau_s` to them (paper A.4 item 1). The presentation term `exp(-r_s * tau_s)` SHALL use the unfloored `r_s`. The boredom alert excess SHALL be unchanged.

#### Scenario: Alerts at a steady base rate leave arousal at baseline
- **WHEN** change alerts arrive every 5 s for 600 s with the module ticking every second
- **THEN** after the first 300 s every alert's habituation factor is 0, and from 450 s arousal stays within 0.01 of baseline

#### Scenario: A burst above the habituated rate raises arousal
- **WHEN** after that habituated stream five change alerts with change ratio 4.0 arrive 0.5 s apart
- **THEN** arousal rises above baseline by at least 0.3

#### Scenario: A first presentation gets the full step
- **WHEN** a fresh module receives one alert with change ratio 3.0
- **THEN** arousal rises by 0.15 x 2.0

#### Scenario: An isolated alert after a long quiet arouses again
- **WHEN** after the habituated stream 600 s pass with no alert and one alert with change ratio 3.0 arrives
- **THEN** its habituation factor is above 0.9 and arousal rises by more than 0.25

#### Scenario: The first alert after a sleep reset gets the full step
- **WHEN** the habituated module is reset by sleep and then receives one alert with change ratio 3.0
- **THEN** arousal rises by 0.15 x 2.0

### Requirement: The novelty check reads the error and change ratios with familiarity
`_score_snapshot` SHALL compute novelty as `1 - prod_e(1 - s_e)` over the selected events whose payload carries a positive finite `normalised_error` or `normalised_change`, with `s_e = clip_[0,1](ln(rho_e) / ln 3)` and `rho_e` the larger of the two ratios, and 0 when no event carries one. For `vision.report` and `audition.perception` events, `s_e` SHALL be multiplied by the habituation factor `h` at the appraisal. The perceived-emotion contribution SHALL be added as before.

#### Scenario: A change alert during a burst is novel
- **WHEN** the alert rates show a burst (`h` = 1) and the coalition holds a vision report with `normalised_error` 0.99 and `normalised_change` 3.0
- **THEN** novelty is 1.0

#### Scenario: A habituated stream is familiar
- **WHEN** `h` is 0 and the coalition holds the same vision report
- **THEN** novelty is 0.0

#### Scenario: Other processors are not discounted
- **WHEN** `h` is 0 and the coalition holds a sequence report with `normalised_error` 3.0
- **THEN** novelty is 1.0

### Requirement: Arousal relaxes toward a drive-raised target
At each affect update the module SHALL relax arousal by `a <- a + (a_inf - a) * min(1, lambda * dt)` with `a_inf = a_0 + gamma_D * (1 - a_0) * v*`, where `a_0` is the baseline arousal, `lambda` is `drift_rate_per_s`, `gamma_D` is `drive_arousal_gain` (default 0.2) and `v*` is the largest drive value at the start of the update (paper A.4 item 3). Dominance SHALL keep relaxing toward its baseline. `gamma_D` SHALL be finite and in `[0, 1]`; with `gamma_D = 0` the update SHALL equal the previous relaxation toward `a_0`.

#### Scenario: A deprived entity rests above baseline
- **WHEN** boredom is held at 0.9 and the other drives at 0, no alert arrives, and the module ticks for 300 s of entity time
- **THEN** arousal is within 0.005 of 0.3 + 0.2 x 0.7 x 0.9 = 0.426

#### Scenario: A satisfied entity rests at baseline
- **WHEN** every drive is 0 and the module ticks from an arousal of 0.8
- **THEN** arousal relaxes to within 0.005 of 0.3

#### Scenario: The sleep reset returns arousal to baseline
- **WHEN** a deprived module at the raised target is reset by sleep
- **THEN** arousal is 0.3 and the next tick's target is 0.3

#### Scenario: A gain of 0 keeps the old relaxation
- **WHEN** the module is built with `drive_arousal_gain = 0` and ticks with deprived drives
- **THEN** every arousal value equals that of the relaxation toward `a_0`

#### Scenario: The gain is validated
- **WHEN** the module is built with `drive_arousal_gain` of -0.1, 1.5 or NaN
- **THEN** construction raises `ValueError`

### Requirement: The sleep reset keeps the habituation, learning-progress and intent estimates
`affective_reset()` SHALL leave the perceptual alert rates `r_f` and `r_s`, the per-source fast and slow error means with their latest report times, the intent rate `r_int` and the intent count since the last broadcast unchanged (paper A.4 item 4). They SHALL continue to change only by their own rules: the alert rates decay at each update with their time constants, the error means are re-weighted by the elapsed time at the next report, and `r_int` updates at each broadcast. The reset SHALL still return valence, arousal and dominance to baseline, set every drive to 0 and re-arm its crossing, set the categorical emotion to neutral, clear the active goals and a speaker's perceived emotion, and keep the last wellness.

#### Scenario: A habituated stream stays habituated after sleep
- **WHEN** a module has habituated to an alert every 5 s for 600 s, is reset by sleep, and the same alerts continue
- **THEN** the habituation factor of the next alert is below 1e-6 and that alert raises arousal by less than 0.001

#### Scenario: The reset does not relieve boredom
- **WHEN** the habituated module is reset and the base-rate alerts continue for 60 s
- **THEN** the alert excess stays 0 throughout

#### Scenario: The estimates survive the reset
- **WHEN** a module with nonzero alert rates, error means and intent rate is reset
- **THEN** each of them equals its value just before the reset, while arousal is at baseline and every drive is 0

#### Scenario: A long quiet still restores the first-presentation response
- **WHEN** the habituated module is reset and then 600 s pass with no alert before one alert with change ratio 3.0
- **THEN** that alert's habituation factor is above 0.9

### Requirement: The entity's own engagement relieves boredom as its own response
The affect module SHALL relieve boredom by `D <- D * (1 - rho_eng)`, with `rho_eng` the `[affect] boredom_engagement_relief` value (default 0.5, in [0, 1]), on each `intent.*` event other than `intent.rest` from the action-selection stream that is not about a drive. An intent is about a drive when its payload `about_kind` is `"felt"` or its `entry_id` names one of the module's own `affect.drive` crossing events (as a qualified `affect.out:<id>` key or a bare id). This relief SHALL count as the entity's own response, so a boredom crossing that falls below its re-arm band through it SHALL raise the boredom drive's own count and complete an active boredom goal with reason `own_response`. An intent about a drive SHALL NOT relieve boredom. Continuous relief by perceptual alert excess SHALL remain and SHALL count as other. When `rho_eng` is 0.0 the module SHALL NOT apply the engagement relief at all, so its behaviour SHALL be identical to the build without it. The sleep reset SHALL be unchanged.

#### Scenario: An engaging intent relieves boredom and counts as own
- **WHEN** boredom has crossed its threshold and an `intent.think` with `about_kind` `"event"` arrives
- **THEN** boredom falls to `D * (1 - rho_eng)`, and if that is below the re-arm band the boredom own count rises and the other count does not

#### Scenario: Novelty alone still counts as other
- **WHEN** a fired boredom drive falls below its re-arm band through alert-excess relief with no intent
- **THEN** its other count rises and its own count does not

#### Scenario: A felt intent does not relieve boredom
- **WHEN** an intent with `about_kind` `"felt"` arrives
- **THEN** boredom is unchanged

#### Scenario: An intent led by a drive crossing does not relieve boredom
- **WHEN** an intent with `about_kind` `"event"` names the coalition key of the module's own `affect.drive` event
- **THEN** boredom is unchanged and restlessness is still relieved

#### Scenario: A boredom goal ended by engagement completes
- **WHEN** a boredom goal is active and an engaging intent takes boredom below its re-arm band
- **THEN** the goal ends `completed` with reason `own_response`

#### Scenario: The sleep reset is unchanged
- **WHEN** the sleep module's affective reset runs
- **THEN** boredom returns to 0 and its own and other counts are unchanged

#### Scenario: Off reproduces the previous behaviour
- **WHEN** `boredom_engagement_relief` is 0.0
- **THEN** a sequence of intents and ticks leaves the drive values, counts, goals and published events identical to the build without the channel

### Requirement: Valence follows error dynamics
At each affect update with `dt > 0` the module SHALL relax valence by `v <- v + (v_inf - v) * (1 - exp(-dt / tau_v))`. Under `valence_rule = "error_dynamics"` (the default) the target SHALL be `v_inf = clip(pl + <w>_f - <w>_s, -1, 1)`, where `pl` is the appraisal's pleasantness check (tanh of `valence_progress_gain` times the signed learning progress, plus the perceived-emotion term) and `<w>_f`, `<w>_s` are time-decayed means of the interoception module's reported wellness with time constants `fast_time_constant_s` and `slow_time_constant_s` (paper A.4). Before any wellness report the difference SHALL be 0. Under `valence_rule = "wellness_level"` the target SHALL be `clip(pl + w - 0.5, -1, 1)` with `w` the last reported wellness, and every published event and the serialized state SHALL equal those of the build before this change. Any other value SHALL raise `ValueError`.

#### Scenario: Falling error raises valence
- **WHEN** a perceptual module's raw error falls steadily and wellness is constant
- **THEN** valence rises above 0

#### Scenario: Rising error lowers valence
- **WHEN** a perceptual module's raw error rises steadily and wellness is constant
- **THEN** valence falls below 0

#### Scenario: A steady healthy host is neutral
- **WHEN** wellness is held at 0.9 with constant perceptual error for 600 s
- **THEN** valence is within 0.01 of 0, where the previous rule rests near 0.4

#### Scenario: Falling wellness lowers valence
- **WHEN** wellness falls from 0.9 to 0.5 with constant perceptual error
- **THEN** valence falls below 0, and it returns toward 0 once wellness is steady

#### Scenario: Valence stays bounded
- **WHEN** errors and wellness take extreme values in any order
- **THEN** valence stays in [-1, 1]

#### Scenario: The previous rule is unchanged
- **WHEN** the module is built with `valence_rule = "wellness_level"` and driven by the same seeded event trace as origin/main
- **THEN** every published event and the serialized state are identical

### Requirement: Wellness means carry through sleep and persist
Under `valence_rule = "error_dynamics"` the wellness means SHALL survive the sleep's affective reset and SHALL be serialized and restored with the module state; invalid stored values SHALL be ignored.

#### Scenario: Sleep keeps the wellness means
- **WHEN** the module resets for sleep after wellness reports
- **THEN** the wellness means are unchanged

#### Scenario: A restore keeps the wellness means
- **WHEN** a module is serialized and a fresh one deserializes the state
- **THEN** the next update gives the same valence target

### Requirement: An active goal's drive event recurs while the drive stays above threshold
The affect module SHALL, on each update, for each active goal with a drive whose value `D` is at or above its threshold, publish an `affect.drive` event with payload `{"drive": <name>, "value": D, "alert": false, "reentry": true}` and intensity `D` when at least `P_re` entity seconds have passed since the goal's crossing or its previous re-entry, with `P_re` the `[affect] concern_reentry_s` value (default 30.0, finite and >= 0). The module SHALL record each re-entry's bus entry id among its drive entry ids, so an intent about it is about a drive. A re-entry SHALL NOT be published for a drive below threshold, for a goal without a drive, or for a goal that is no longer active, and the schedule SHALL be cleared when the goal ends and on the sleep reset. When `P_re` is 0 the module SHALL publish no re-entry and keep no re-entry state, so its behaviour SHALL be identical to the build without it.

#### Scenario: A sustained drive re-enters at its value
- **WHEN** a drive crossed at entity time 0, its goal stays active and the drive stays at or above threshold
- **THEN** a re-entry is published at the first update at or after `P_re`, then again `P_re` after it, each with intensity equal to the drive's value and `alert` false

#### Scenario: No re-entry below threshold
- **WHEN** the drive of an active goal is below its threshold at an update past its due time
- **THEN** no re-entry is published, and one is published at the first later update with the drive at or above threshold

#### Scenario: Re-entry stops when the goal ends
- **WHEN** the goal completes, is abandoned (including the stall horizon) or is cleared by the sleep reset
- **THEN** no further re-entry for it is published

#### Scenario: An intent about a re-entry does not relieve boredom
- **WHEN** an intent names the coalition key of a boredom re-entry
- **THEN** boredom is unchanged and restlessness is relieved

#### Scenario: Off reproduces the previous behaviour
- **WHEN** `concern_reentry_s` is 0
- **THEN** a sequence of ticks and intents leaves the drive values, goals and published events identical to the build without re-entry

### Requirement: A sustained concern's drive event recurs until a broadcast accesses it
With `P_re` (`[affect] concern_reentry_s`) above 0, the affect module SHALL keep each active goal's latest drive event (its crossing, then each re-entry) pending until a broadcast accesses it, meaning a broadcast that is not inhibited carries it as a coalition member with a score at or above the broadcast's access threshold. While the event is pending and the goal's drive `D` is at or above its threshold, the module SHALL republish it on each of its own `P_Aff` timer updates as an `affect.drive` event with payload `{"drive": <name>, "value": D, "alert": false, "reentry": true}` and intensity `D`, at most once per goal per update and only when the previous copy is at least `P_Aff / 2` old. After an access the module SHALL publish the goal's next re-entry at the first timer update at least `P_re` after the access. Updates triggered by a broadcast SHALL NOT publish re-entries or copies. Every published copy's bus entry id SHALL join the module's drive entry ids. Pending state SHALL be cleared when the goal ends, on the sleep reset and on restore. When `P_re` is 0 the module SHALL behave bit for bit as the build without re-entry.

#### Scenario: A missed crossing recurs until accessed
- **WHEN** a drive crosses its threshold and no broadcast accesses the crossing
- **THEN** each later timer update at least `P_Aff / 2` after the previous copy publishes a re-entry at the drive's value, until a broadcast accesses one of them

#### Scenario: The interval runs from the access
- **WHEN** a broadcast accesses the goal's pending drive event at entity time `t`
- **THEN** no copy is published before `t + P_re`, and the next re-entry is published at the first timer update at or after `t + P_re`

#### Scenario: A broadcast that does not access it leaves it pending
- **WHEN** a broadcast carries the pending event below the access threshold, is inhibited, or does not carry it
- **THEN** the event stays pending and recurs at the next eligible timer update

#### Scenario: Broadcast-triggered updates publish no re-entry
- **WHEN** the module updates in response to a broadcast while a re-entry is due or an event is pending
- **THEN** it publishes no re-entry and no copy on that update

#### Scenario: Stops when the goal ends, on sleep and on restore
- **WHEN** the goal completes, is abandoned or cleared, the sleep reset runs, or the module is restored
- **THEN** no further copy for that goal is published from the old pending state

#### Scenario: Off is unchanged
- **WHEN** `concern_reentry_s` is 0
- **THEN** a sequence of updates, broadcasts and intents leaves drives, goals and published events identical to the build without re-entry

### Requirement: The goal stall clock persists across a restore
The affect module SHALL store, for each active goal whose drive is at or above its threshold with a running stall clock, the elapsed entity seconds since the clock started, under `goal_above_elapsed` in its serialized state. On restore it SHALL set each restored active goal's stall start to the restore time minus that elapsed time, so the goal is abandoned as `stalled` once its total above-threshold time reaches `goal_stall_s` (`Delta_stall`, paper A.4, Table A1). State without `goal_above_elapsed`, and entries that are not a finite non-negative number or name no active goal, SHALL restore as before: the stall clock starts at the first update after the restore.

#### Scenario: A restored goal keeps its stall horizon
- **WHEN** a goal's drive has stayed above threshold for 4 s with `goal_stall_s` 5, the module is serialized and restored into a fresh clock, and the drive stays above threshold for 1 more second
- **THEN** the goal is abandoned with reason `stalled`

#### Scenario: Older state restarts the clock
- **WHEN** the same state is restored without `goal_above_elapsed`
- **THEN** the goal stays active until 5 s after the first update following the restore

#### Scenario: An invalid entry is ignored
- **WHEN** `goal_above_elapsed` holds a negative, non-finite, boolean or non-numeric value, or names an unknown goal
- **THEN** that goal's stall clock restarts at the first update after the restore and the restore raises no error

### Requirement: Goal relevance is scored in [0, 1] against the entity's dominant drive
The affect module's goal-significance appraisal check SHALL score the selected events against the entity's dominant drive (the highest-valued affect drive, ties broken by name), using the drive-to-source table built from each registered module's `relieves_drives` declaration and injected by the boot wiring and re-injected when the affect module is restarted. With dominant drive value `v > 0` and `f` the salience-weighted share of selected events whose source relieves that drive (`0` for an empty coalition or a zero total), the drive score SHALL be `v × f`. With no drive above zero, the drive score SHALL be `0.0`. When the goal ledger holds active goals, the check SHALL return the larger of the drive score and the ledger `relevance` (the ledger relevance alone when no table was injected); otherwise it SHALL return the drive score, or `0.0` when no table was injected. The score SHALL lie in `[0, 1]`: content that serves neither the drive nor a goal is irrelevant, not obstructive. No constant offset SHALL be applied.

#### Scenario: Content serving a pressing need is goal-conducive
- **WHEN** the social drive is the dominant drive at 0.8 and every selected event comes from a source that relieves the social drive
- **THEN** goal significance is 0.8

#### Scenario: Content ignoring a pressing need is irrelevant
- **WHEN** the social drive is the dominant drive at 0.8 and no selected event comes from a source that relieves it
- **THEN** goal significance is 0.0

#### Scenario: An empty coalition is irrelevant
- **WHEN** the curiosity drive is the dominant drive at 0.3 and the coalition is empty
- **THEN** goal significance is 0.0

#### Scenario: An idle coalition does not classify as anger
- **WHEN** the dominant drive is unmet, no selected event relieves it, and affect is at baseline
- **THEN** the categorical emotion is not `anger`

#### Scenario: No pressing need
- **WHEN** every drive is at 0.0 and no goals are active
- **THEN** goal significance is 0.0

### Requirement: Goals come from drive crossings
On each crossing of a drive's threshold the affect module SHALL create the goal of relieving that drive, with priority equal to the drive value at the crossing and expected-relief likelihood `L` equal to that drive's success ratio `(s + 1) / (s + f + 2)`, unless that drive already has an active goal. Intents SHALL NOT create goals. Each creation SHALL publish an `affect.goal` event with `action: "added"`, the drive and `L`.

#### Scenario: A crossing creates a goal
- **WHEN** curiosity crosses its threshold at 0.72 with no active curiosity goal, one own end and no other ends
- **THEN** the ledger holds one active goal for curiosity with priority 0.72 and `L` 2/3, and an `affect.goal` event with `action: "added"` is published

#### Scenario: A drive keeps one goal
- **WHEN** curiosity crosses its threshold again while its goal is still active
- **THEN** no second curiosity goal is created

### Requirement: Drive goals end by the credit rule, a stall or the cap
A drive goal SHALL complete when its drive falls below the re-arm band and the credit rule counts the end as the entity's own response. It SHALL be abandoned when the credit rule counts the end as another's, when the drive stays at or above its threshold for `goal_stall_s` entity seconds without an update seeing it below, or when active goals exceed `goal_cap`, in which case the lowest-priority active goal, ties going to the earliest created, SHALL be abandoned. Each end SHALL publish an `affect.goal` event and count in the ledger's completed or abandoned total.

#### Scenario: Own relief completes the goal
- **WHEN** an intent relieves an active restlessness goal's drive below its re-arm band
- **THEN** the goal is completed and the ledger's completed count rises by one

#### Scenario: Relief by another abandons the goal
- **WHEN** another's voice relieves an active social-drive goal's drive below its re-arm band
- **THEN** the goal is abandoned and the ledger's abandoned count rises by one

#### Scenario: A stalled goal is abandoned
- **WHEN** a goal's drive stays at or above its threshold for `goal_stall_s`
- **THEN** the goal is abandoned

#### Scenario: The cap abandons the lowest priority
- **WHEN** a fourth drive goal is created with `goal_cap` 3 and priorities 0.71, 0.80, 0.75 and 0.90
- **THEN** the goal with priority 0.71 is abandoned and three stay active

### Requirement: Unanswered responses obstruct the dominant drive's goal
For each intent other than `intent.rest` made while a drive goal is active, the affect module SHALL record the drive's value just before the intent. When no update within `goal_response_window_s` sees the drive below that value, the goal's `L` SHALL fall by `ΔL = goal_likelihood_fall × L`, and `ΔL` SHALL be held for the next appraisal. That appraisal SHALL take the obstruction `o = v* × ΔL` when the held `ΔL` belongs to the dominant drive's goal and `o = 0` otherwise, and SHALL clear every held `ΔL`. The goal score SHALL be `clip(r - o, -1, 1)`, with `r` the conducive part. Coping SHALL be checked whenever the goal score is nonzero. `affect.emotion` SHALL carry the `obstruction` applied.

#### Scenario: An unanswered intent lowers the likelihood
- **WHEN** an intent is made while a curiosity goal with `L` 0.5 is active and curiosity does not fall within `goal_response_window_s`
- **THEN** `L` becomes 0.25 and the next appraisal, with curiosity dominant at 0.8 and irrelevant content, has goal score -0.2

#### Scenario: A fall within the window leaves the likelihood
- **WHEN** an intent relieves restlessness while a restlessness goal is active
- **THEN** `L` is unchanged and the next appraisal has obstruction 0

#### Scenario: A non-dominant goal does not obstruct
- **WHEN** a held `ΔL` belongs to a goal whose drive is not dominant at the next appraisal
- **THEN** that appraisal has obstruction 0 and the held `ΔL` is cleared

#### Scenario: Obstruction with high power yields anger
- **WHEN** the goal score is at or below -0.3 and the dominant drive's success ratio gives coping at least 0.3
- **THEN** the categorical emotion is `anger`

#### Scenario: Nothing changes without an active goal
- **WHEN** no goal is active
- **THEN** the appraisal scores equal those computed without the goal rules

### Requirement: The sleep reset clears active goals and goals persist
The affective reset SHALL remove every active goal without counting it as completed or abandoned, and SHALL clear the response windows and held obstruction. Serialize and deserialize SHALL preserve every goal with its drive and `L`, and the ledger's completed and abandoned counts. The ledger SHALL retain at most 256 finished goals while its counts include pruned ones.

#### Scenario: Sleep removes active goals
- **WHEN** the affective reset runs with two active goals
- **THEN** no goal is active and the completed and abandoned counts are unchanged

#### Scenario: Goals survive preservation
- **WHEN** an affect module with an active curiosity goal at `L` 0.25 is serialized and a new instance deserializes the state
- **THEN** the new instance holds the active curiosity goal with `L` 0.25

### Requirement: The affect state event carries the valence-target terms
Every `affect.state` payload, periodic or after an affective reset, SHALL carry, in addition to its existing keys, the terms behind the valence target computed at publication: for each source in the fixed table (`vision`, `audition`) the keys `<source>_error_fast`, `<source>_error_slow` and `<source>_progress` (the fast and slow time-decayed means of its raw prediction error and its clipped relative fall `g_m`); `signed_progress` (the pooled `g`, paper `lp`); `learning_progress` (paper `lp+`); `wellness`; `wellness_fast`, `wellness_slow` and `wellness_change`; `pleasantness`; and `valence_target` under the active `valence_rule`. A source absent from the trackers SHALL give null for its three keys, and a source whose slow mean is not above 1e-9 SHALL give a null progress. The wellness means SHALL be null before the first wellness report, and `wellness_change` SHALL be the value the error-dynamics rule adds (0.0 before reports). Every value SHALL be a finite number or null, and the key set SHALL NOT depend on which sources have reported. The values SHALL equal the ones the update step uses, and the affect dynamics SHALL be unchanged.

#### Scenario: Values match the trackers
- **WHEN** vision has reported known errors at known times, interoception has reported known wellness values, and the module publishes `affect.state`
- **THEN** `vision_error_fast`, `vision_error_slow` and `vision_progress` equal the time-decayed means and `g_m` computed from those reports, `signed_progress` and `learning_progress` equal `_progress()`, `wellness_change` equals the fast minus the slow wellness mean, and `valence_target` equals `clip(tanh(valence_progress_gain * g) + wellness_change, -1, 1)`

#### Scenario: An absent source is null
- **WHEN** only vision has reported
- **THEN** `audition_error_fast`, `audition_error_slow` and `audition_progress` are null and the payload has the same keys as when both sources have reported

#### Scenario: An unlisted source adds no keys
- **WHEN** a perceptual report arrives from a source outside the table
- **THEN** it counts in `signed_progress` and the payload's key set is unchanged

### Requirement: Learning progress compares windowed error means
For each perceptual source the affect module SHALL sum the raw `prediction_error` of its reports, counted from the source's first positive error, into consecutive bins of `learning_progress_bin_s` of entity time. With `k` the number of the latest completed bins, at most `learning_progress_span_s / learning_progress_bin_s` and rounded down to an even number, the source's learning progress SHALL be `clip(1 - mean_new / mean_old, -1, 1)`, where `mean_old` and `mean_new` are the report-weighted mean errors of the older and newer halves of those `k` bins, and it SHALL be undefined while `k < 2`, while either half holds no report, or while `mean_old <= 1e-9`. The pooled learning progress `lp` SHALL be the mean over sources with a defined value, 0.0 if none, and `lp+ = max(0, lp - learning_progress_floor) / (1 - learning_progress_floor)` SHALL be the curiosity relief strength and `1 - lp+` its build input (paper A.4). The fast and slow time-decayed error means and their pooled relative fall SHALL keep setting the pleasantness check, unchanged.

#### Scenario: Falling error gives progress
- **WHEN** a source reports an error that falls 30 percent from the older to the newer half of the span
- **THEN** its learning progress is 0.3 and `lp+` relieves curiosity

#### Scenario: Flat error gives none
- **WHEN** a source reports a constant error for longer than the span
- **THEN** its learning progress is 0 and curiosity is not relieved

#### Scenario: The span grows from the first report
- **WHEN** a source has completed one bin
- **THEN** its learning progress is undefined, and after two completed bins it compares the first bin with the second

#### Scenario: Valence is unchanged
- **WHEN** the same reports arrive as in the build before this change
- **THEN** `signed_progress`, the pleasantness and the valence target equal that build's values

### Requirement: Learning-progress configuration
The `[affect]` section SHALL accept `learning_progress_span_s` (default 5400.0) and `learning_progress_bin_s` (default 60.0). Both SHALL be finite and positive, and the span SHALL be an even whole number of bins, at least 2, or construction SHALL raise `ValueError`.

#### Scenario: A span that is not an even number of bins is refused
- **WHEN** the affect module is built with `learning_progress_span_s = 150.0` and `learning_progress_bin_s = 60.0`
- **THEN** it raises `ValueError`

### Requirement: Learning-progress bins persist
The affect snapshot SHALL carry each source's completed bins, its current bin and the entity time elapsed in it under `learning_progress_bins`, with the bin width, and a restore SHALL reproduce the source's learning progress. A snapshot without the key, an entry with invalid numbers, or one saved with a different bin width SHALL leave that source's bins empty; more bins than the span SHALL keep the newest. The bins SHALL carry through sleep like the error means.

#### Scenario: Round trip
- **WHEN** a module with bins for vision and audition is serialized and a fresh module deserializes the state
- **THEN** both report the same learning progress

#### Scenario: Old snapshot
- **WHEN** a snapshot saved before this change is restored
- **THEN** the error means are restored and the learning-progress bins start empty

### Requirement: The affect state event carries the windowed progress terms
Every `affect.state` payload SHALL carry `vision_learning_progress` and `audition_learning_progress`, each source's windowed learning progress or null while undefined, and `signed_learning_progress`, the pooled `lp`. `learning_progress` SHALL be `lp+` from the windows. Every value SHALL be finite or null and the key set SHALL be fixed.

#### Scenario: Terms match the estimator
- **WHEN** vision has reported for several bins and the module publishes `affect.state`
- **THEN** `vision_learning_progress` equals the estimator's value, `audition_learning_progress` is null, and `signed_learning_progress` equals `vision_learning_progress`

### Requirement: The affect state event carries each drive's threshold flag and crossing-end counts
Every `affect.state` event, the periodic one and the one after a sleep reset, SHALL carry `drive_above`, mapping each drive name to whether its value is at or above its threshold, and `drive_ends`, mapping each drive name to its cumulative `own` and `other` crossing-end counts, the counts the coping drive term uses (paper A.4). Both SHALL hold only booleans and non-negative integers keyed by drive name.

#### Scenario: A deprived drive is flagged
- **WHEN** curiosity is at 0.9 with threshold 0.7 and boredom at 0.2
- **THEN** the next `affect.state` event has `drive_above.curiosity` true and `drive_above.boredom` false

#### Scenario: The reset event carries the counts
- **WHEN** a sleep reset follows one own end of curiosity
- **THEN** the reset `affect.state` event has `drive_ends.curiosity` equal to `{"own": 1, "other": 0}` and every `drive_above` entry false

### Requirement: Curiosity is heterostatic interest raised by learning progress
The affect module SHALL build curiosity with input `u = lp+` by the exact drive step, with decay `delta_I` (default 0.00096 per second, at which a sustained `lp+` of 0.045 holds curiosity at `theta_D`) and no relief. A curiosity crossing SHALL publish its `affect.drive` event and SHALL NOT create a goal. Curiosity falling back below its re-arm band SHALL re-arm its crossing without counting an own or other end.

#### Scenario: Nothing learnable leaves curiosity at rest
- **WHEN** learning progress stays 0 for an hour
- **THEN** curiosity stays at 0 and no curiosity crossing is published

#### Scenario: A progress niche raises curiosity without a goal
- **WHEN** `lp+` stays at 0.1 until curiosity crosses `theta_D`
- **THEN** an `affect.drive` event for curiosity is published, the goal ledger holds no curiosity goal, and curiosity's own and other end counts stay 0 after it decays back below the band

### Requirement: Boredom is also met by learning progress
Each update SHALL relieve boredom at strength `max(lp+, exc)` and build it with input `1 - max(lp+, exc)`. The relief SHALL count as the entity's own response when `lp+` is positive and at least `exc`, and a fall back below the band on a step SHALL count as own when it would not have happened at the no-response build input `1 - exc`.

#### Scenario: Learning ends a boredom crossing as the entity's own
- **WHEN** boredom is above threshold, `exc` is 0 and `lp+` is 0.3 until boredom falls below its band
- **THEN** boredom's own end count rises by one

### Requirement: Arousal, sleep reset and goals apply to deficits
The tonic arousal target SHALL use the largest value among boredom, the social drive and restlessness. The sleep reset SHALL set those three drives to 0 and re-arm their crossings, and SHALL keep curiosity's value and crossing latch.

#### Scenario: Interest survives sleep
- **WHEN** curiosity is 0.8 with its crossing latched and the sleep reset runs
- **THEN** curiosity is still 0.8 and latched, and boredom is 0

### Requirement: Older checkpoints migrate curiosity
The affect state SHALL carry `curiosity_scheme` 2. Restoring state without it SHALL set curiosity to 0 with its latch clear and its end counts 0, and SHALL remove any active curiosity goal without publishing an `affect.goal` event; the other drives, counts and goals restore unchanged.

#### Scenario: A deficit-era checkpoint
- **WHEN** a state without `curiosity_scheme` holds curiosity 0.9, latched, with 3 own ends and an active curiosity goal
- **THEN** after restore curiosity is 0, unlatched, with 0 own and 0 other ends, and no curiosity goal is active
