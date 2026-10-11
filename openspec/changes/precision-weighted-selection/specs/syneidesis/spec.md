## ADDED Requirements

### Requirement: Arousal sharpens contrast above baseline
The v1 salience strategy SHALL score a candidate as the arousal level factor times a contrast function of its priority. The contrast function SHALL be the logistic function of slope `g` centred at one half, rescaled to map 0 to 0 and 1 to 1, and SHALL be the identity when `g` is zero. The slope SHALL be zero at or below baseline arousal and SHALL rise linearly to the configured contrast gain at full arousal.

#### Scenario: Identity at baseline arousal
- **WHEN** arousal is at its baseline
- **THEN** each score equals the level factor times the priority

#### Scenario: Contrast at full arousal
- **WHEN** arousal is 1.0 with the default contrast gain of 8
- **THEN** a priority of 0.8 maps to about 0.93 and a priority of 0.2 to about 0.07 before the level factor
