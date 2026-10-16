## ADDED Requirements

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
Tier 2 SHALL re-run the appraisal of the last broadcast against the current coping and goal state and move valence toward the re-run valence target `clip(pl + w - 1/2, -1, 1)` by `reappraisal_fraction` of the difference, at most once per episode, leaving arousal unchanged. Its `size` SHALL be the valence change.

#### Scenario: Reappraisal moves valence by the fraction
- **WHEN** tier 2 fires with valence -0.6, a re-run valence target of -0.2 and `reappraisal_fraction` 0.5
- **THEN** valence becomes -0.4 and the event's `size` is 0.2

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
