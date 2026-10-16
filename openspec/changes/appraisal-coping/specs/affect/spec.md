## ADDED Requirements

### Requirement: Coping potential is gated by relevance and estimated as a success ratio
The affect module SHALL compute coping potential only when the goal score is above 0. When the goal score is 0, coping SHALL be unavailable: the appraisal scores SHALL carry `coping_available = False` with a numeric coping value of 0.0, and `classify()` SHALL NOT return fear, anger or sadness. When coping is available it SHALL be `2p - 1` with `p = (s + 1) / (s + f + 2)`. When the drive term sets the goal score (including a tie with the ledger term), `s` and `f` SHALL be the dominant drive's crossings ended by relief and by decay alone; when the ledger term sets it, `s` and `f` SHALL be the ledger's completed and abandoned goals. A crossing ends when the drive falls below its re-arm band; it ends by relief when that fall happens in `relieve` or `relieve_rate`, by decay when it happens in `tick`, and a sleep reset SHALL count as neither. Arousal and valence SHALL NOT enter coping. The drive counts SHALL survive serialize and deserialize. The `affect.emotion` payload SHALL carry `coping_available`.

#### Scenario: Irrelevant content leaves coping unavailable
- **WHEN** the goal score is 0.0, pleasantness is -0.6 and novelty is 0.1
- **THEN** `coping_available` is false and the categorical emotion is neither `fear`, `anger` nor `sadness`

#### Scenario: No history gives neutral coping
- **WHEN** the dominant drive sets a goal score above 0 and has no ended crossings
- **THEN** coping is 0.0

#### Scenario: Crossings ended by decay lower coping
- **WHEN** the dominant drive sets the goal score and two of its crossings ended by decay and none by relief
- **THEN** coping is -0.5

#### Scenario: Crossings ended by relief raise coping
- **WHEN** the dominant drive sets the goal score and two of its crossings ended by relief and none by decay
- **THEN** coping is 0.5

#### Scenario: The ledger supplies power when it sets the score
- **WHEN** the ledger term exceeds the drive term and the ledger holds one completed and three abandoned goals
- **THEN** coping is 2 × (2 / 6) - 1

#### Scenario: Arousal does not move coping
- **WHEN** arousal changes and the drive and ledger counts do not
- **THEN** coping is unchanged

#### Scenario: Counts survive preservation
- **WHEN** the affect module is serialized and a new instance deserializes the state
- **THEN** every drive's relief and decay counts are restored
