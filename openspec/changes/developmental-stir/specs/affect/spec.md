## ADDED Requirements

### Requirement: A stir relieves restlessness without engagement relief
The affect module SHALL count an `intent.stir` as an intent other than rest: it SHALL enter the intent rate that restlessness builds against and SHALL relieve restlessness by its relief gain. Because a stir is about a drive, it SHALL NOT apply the engagement relief to boredom.

#### Scenario: A stir during restlessness
- **WHEN** restlessness is at 0.7 and the entity stirs
- **THEN** restlessness falls by its relief gain and boredom is not relieved by the stir itself

### Requirement: Only relief attributable to an answer is the entity's own
A boredom crossing's end SHALL count as the entity's own response through a stir only when it comes during an answer or within `Δ_resp` after the answer's end, the relief came through audition's alert excess or learning progress, and no scheduled stimulus event (maternal speech, an added sound, a hearing-band step or a colour step) overlaps that window. Any other end SHALL be attributed by the existing rule, with other perceptual novelty counted as other.

#### Scenario: Boredom falls during an answer
- **WHEN** boredom falls below its re-arm level through audition's alert excess 3 s into an answer, with no scheduled event in the window
- **THEN** the crossing's end counts as own in `drive_ends`

#### Scenario: Scheduled speech overlaps the window
- **WHEN** boredom falls during an answer's window and a scheduled maternal utterance started inside that window
- **THEN** the end is not counted as own through the stir

#### Scenario: Boredom falls long after an answer
- **WHEN** boredom falls 60 s after an answer ended, with no stir since
- **THEN** the end is attributed as it would be without the stir
