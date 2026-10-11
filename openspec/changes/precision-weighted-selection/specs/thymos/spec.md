## ADDED Requirements

### Requirement: The modulator reports a contrast gain
Thymos's state modulator SHALL report a contrast gain that is zero when arousal is at or below the baseline arousal and rises linearly to the configured `arousal_contrast_gain` at arousal 1.0. A static modulator SHALL report zero.

#### Scenario: No contrast at baseline
- **WHEN** arousal equals the baseline arousal
- **THEN** the contrast gain is 0.0
