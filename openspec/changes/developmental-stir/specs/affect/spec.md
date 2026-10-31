## ADDED Requirements

### Requirement: A stir relieves restlessness without engagement relief
The affect module SHALL count an `intent.stir` as an intent other than rest: it SHALL enter the intent rate that restlessness builds against and SHALL relieve restlessness by its relief gain. Because a stir is about a drive, it SHALL NOT apply the engagement relief to boredom.

#### Scenario: A stir during restlessness
- **WHEN** restlessness is at 0.7 and the entity stirs
- **THEN** restlessness falls by its relief gain and boredom is not relieved by the stir itself

### Requirement: An answer's novelty ends boredom as the entity's own response
When a boredom crossing ends through learning progress or alert excess during an answer to a stir or within `Δ_resp` after the answer's end, as reported by `development.stir_answer`, the affect module SHALL count the end as the entity's own response.

#### Scenario: Boredom falls during an answer
- **WHEN** boredom falls below its re-arm level through alert excess 3 s into an answer
- **THEN** the crossing's end counts as own in `drive_ends`

#### Scenario: Boredom falls long after an answer
- **WHEN** boredom falls 60 s after an answer ended, with no stir since
- **THEN** the end is attributed as it would be without the stir
