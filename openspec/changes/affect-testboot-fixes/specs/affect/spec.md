## ADDED Requirements

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

## MODIFIED Requirements

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
