## ADDED Requirements

### Requirement: Dimensional state with homeostatic drift
Thymos SHALL maintain a `DimensionalState` containing `valence`
(float in `[-1, 1]`), `arousal` (float in `[0, 1]`), and `dominance`
(float in `[-1, 1]`). On every internal tick the state SHALL drift
toward its configured baseline by a configurable fraction
(`drift_rate_per_s`) of the elapsed wall time, clamped to the valid
range for each dimension.

#### Scenario: Drift moves valence toward baseline
- **WHEN** the state has `valence=0.8`, the baseline is 0.0, and
  `drift_rate_per_s=0.5` is applied for 2.0 seconds
- **THEN** the new valence is between 0.0 and 0.8 (strictly less
  than the prior value)

#### Scenario: Clamping enforced on out-of-range inputs
- **WHEN** an update attempts to set `arousal=1.5`
- **THEN** the resulting state has `arousal == 1.0`

### Requirement: Scherer CPM five-check appraisal produces categorical emotions
Thymos SHALL run an appraisal sequence implementing Scherer's
Component Process Model: five callables in order (novelty,
intrinsic_pleasantness, goal_significance, coping_potential,
norm_compatibility), each returning a score in `[-1, 1]`. The
resulting 5-tuple SHALL be mapped to one of seven categorical
emotions via a pure function `classify(scores) -> CategoricalEmotion`:
`joy`, `sadness`, `anger`, `fear`, `surprise`, `disgust`, `neutral`.

#### Scenario: Positive pleasantness + positive goal yields joy
- **WHEN** `classify((novelty=0.2, pleasantness=0.7, goal=0.6,
  coping=0.5, norm=0.3))` is invoked
- **THEN** the returned emotion is `CategoricalEmotion.JOY`

#### Scenario: Negative pleasantness + negative coping yields fear
- **WHEN** `classify((novelty=0.7, pleasantness=-0.6, goal=0.2,
  coping=-0.5, norm=0.0))` is invoked
- **THEN** the returned emotion is `CategoricalEmotion.FEAR`

#### Scenario: Near-zero across the board yields neutral
- **WHEN** every score is within `±0.1` of zero
- **THEN** the returned emotion is `CategoricalEmotion.NEUTRAL`

### Requirement: Four drive states with build, threshold, and hysteresis
Thymos SHALL maintain four drive accumulators: `curiosity`,
`boredom`, `social_drive`, `restlessness`. Each SHALL be a float in
`[0, 1]`. Each `tick(dt, signals)` SHALL increment the drive by its
configured build rate (modulated by the relevant signal) and decay it
toward 0 by its decay rate. When a drive crosses its threshold,
Thymos SHALL publish a `thymos.drive` event at alert salience. The
drive SHALL only re-fire after dropping below `threshold * 0.9`
(hysteresis) — no event storms from a value oscillating around the
threshold.

#### Scenario: Crossing threshold publishes one drive event
- **WHEN** curiosity's value rises from 0.5 to 0.75 in one tick and
  its threshold is 0.7
- **THEN** exactly one `thymos.drive` event is published with
  `drive="curiosity"`

#### Scenario: Hysteresis prevents re-fire above threshold
- **WHEN** a drive that just fired is updated to a value still
  exceeding its threshold but it has not yet dropped below
  `threshold * 0.9` since the prior fire
- **THEN** no additional `thymos.drive` event is published

### Requirement: Goal ledger supports add/complete/abandon and relevance scoring
Thymos SHALL expose a `GoalLedger` with `add(description, priority)`
returning a goal id, plus `complete(id)`, `abandon(id)`, and
`relevance(event) -> float`. Each lifecycle change SHALL publish a
`thymos.goal` event. `relevance` SHALL return a float in `[0, 1]`
based on token overlap between active goal descriptions and the
event's source/type/payload string, weighted by goal priority.

#### Scenario: Add publishes a thymos.goal event
- **WHEN** `ledger.add("explore the perimeter", priority=0.6)` is
  called
- **THEN** a `thymos.goal` event is published with `action="added"`,
  the returned id, and the description

#### Scenario: Completed goals do not contribute to relevance
- **WHEN** a goal is completed and `relevance(event)` is called with
  an event that strongly overlaps that goal's description
- **THEN** the returned relevance does not include any contribution
  from the completed goal

### Requirement: ThymosModulator exposes salience multiplier to Syneidesis
Thymos SHALL expose an instance implementing Syneidesis's existing
`ThymosModulator` protocol (`async modulate(event) -> float in
[0, 1]`). The returned multiplier SHALL be a function of the current
dimensional state — at least, higher arousal SHALL produce a strictly
larger multiplier than lower arousal for the same event.

#### Scenario: Higher arousal yields larger multiplier
- **WHEN** `modulate(event)` is called once with `arousal=0.2` and
  again with `arousal=0.8`
- **THEN** the second call returns a strictly greater value

### Requirement: Affective reset entry point for Hypnos
Thymos SHALL expose `async affective_reset()` that snaps the
dimensional state to its configured baseline and decays every drive
to zero in a single call. Phase 6 Hypnos calls this during sleep.

#### Scenario: Reset restores baseline and zeroes drives
- **WHEN** state is `valence=0.7, arousal=0.8` and a drive is at 0.9,
  and `affective_reset()` is awaited
- **THEN** the state equals the configured baseline and every drive
  is 0.0

### Requirement: Default Thymos config and disabled-by-default
The repository SHALL ship a `[thymos]` block in `config/kaine.toml`
with default values for `baseline_valence`, `baseline_arousal`,
`baseline_dominance`, `drift_rate_per_s`, per-drive build/decay/
thresholds, appraisal weights, `publish_interval_s`,
`baseline_salience`, and `alert_salience`. `[modules].thymos = false`
SHALL keep first boot from auto-registering Thymos.

#### Scenario: kaine.toml carries defaults
- **WHEN** an operator inspects `config/kaine.toml`
- **THEN** they find a `[thymos]` section with the documented keys
  and `[modules].thymos == false`
