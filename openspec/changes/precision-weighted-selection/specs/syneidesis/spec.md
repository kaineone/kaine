## ADDED Requirements

### Requirement: Candidates are weighted by their source's precision
When precision weighting is enabled, Syneidesis's v1 salience strategy SHALL weight each candidate's intensity by its source's precision weight: the square root of the source's precision (the inverse of the running variance of the intensities it publishes, plus a floor) relative to the geometric mean precision of all warmed sources, clipped to the configured bounds. The weight SHALL be computed from the statistics before the candidate's own update and SHALL be 1.0 for every source until at least three sources have the configured number of events. A strategy built without a precision tracker SHALL use a weight of 1.0.

#### Scenario: Habitual alerts count for less
- **WHEN** one source alternates between its baseline and alert intensity on every event and another source publishes its baseline almost always, after both and a third source have warmed up
- **THEN** the alternating source's weight is below 1.0 and the steady source's weight is above it

#### Scenario: No tracker is neutral
- **WHEN** the strategy is built without a precision tracker
- **THEN** every candidate's precision weight is 1.0

### Requirement: Arousal sharpens contrast above baseline
The v1 salience strategy SHALL score a candidate as the arousal level factor times a contrast function of its priority. The contrast function SHALL be the logistic function of slope `g` centred at one half, rescaled to map 0 to 0 and 1 to 1, and SHALL be the identity when `g` is zero. The slope SHALL be zero at or below baseline arousal and SHALL rise linearly to the configured contrast gain at full arousal.

#### Scenario: Identity at baseline arousal
- **WHEN** arousal is at its baseline
- **THEN** each score equals the level factor times the priority

#### Scenario: Contrast at full arousal
- **WHEN** arousal is 1.0 with the default contrast gain of 8
- **THEN** a priority of 0.8 maps to about 0.93 and a priority of 0.2 to about 0.07 before the level factor
