## ADDED Requirements

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

## MODIFIED Requirements

### Requirement: Coping potential is gated by relevance and estimated as a success ratio
The affect module SHALL compute coping potential only when the goal score is nonzero. When the goal score is 0, coping SHALL be unavailable: the appraisal scores SHALL carry `coping_available = False` with a numeric coping value of 0.0, and `classify()` SHALL NOT return fear, anger or sadness. When coping is available it SHALL be `2p - 1` with `p = (s + 1) / (s + f + 2)`. When the drive term sets the conducive part of the goal score (including a tie with the ledger term), `s` SHALL be the dominant drive's crossings ended by the entity's own response and `f` those ended any other way; when the ledger term sets it, `s` and `f` SHALL be the ledger's completed and abandoned goals. Arousal and valence SHALL NOT enter coping.

#### Scenario: Irrelevant unobstructed content leaves coping unavailable
- **WHEN** the goal score is 0.0, pleasantness is -0.6 and novelty is 0.1
- **THEN** `coping_available` is false and the categorical emotion is neither `fear`, `anger` nor `sadness`

#### Scenario: A negative goal score makes coping available
- **WHEN** the conducive part is 0 and the obstruction is 0.2
- **THEN** the goal score is -0.2 and `coping_available` is true
