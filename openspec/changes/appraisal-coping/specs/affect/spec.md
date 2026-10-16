## ADDED Requirements

### Requirement: Coping potential is gated by relevance and estimated as a success ratio
The affect module SHALL compute coping potential only when the goal score is above 0. When the goal score is 0, coping SHALL be unavailable: the appraisal scores SHALL carry `coping_available = False` with a numeric coping value of 0.0, and `classify()` SHALL NOT return fear, anger or sadness. When coping is available it SHALL be `2p - 1` with `p = (s + 1) / (s + f + 2)`. When the drive term sets the goal score (including a tie with the ledger term), `s` SHALL be the dominant drive's crossings ended by the entity's own response and `f` those ended any other way; when the ledger term sets it, `s` and `f` SHALL be the ledger's completed and abandoned goals. A crossing ends when the drive falls below its re-arm band. It SHALL count as own when the fall happens in a relief whose source is the entity's own response (learning progress for curiosity, intents for restlessness), or in `tick` when the entity's response held the build input below its no-response value and a counterfactual step at that value would not have fallen below the band. Every other end SHALL count as other, and a sleep reset SHALL count as neither. Arousal and valence SHALL NOT enter coping. The drive counts SHALL survive serialize and deserialize. The `affect.emotion` payload SHALL carry `coping_available`.

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
