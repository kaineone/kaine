## ADDED Requirements

### Requirement: One distress episode counts once
The protective monitor SHALL count one sustained-distress episode once toward its repeat window, and both sustained-distress detectors SHALL take their parameters from one configuration source.

#### Scenario: One distress episode counts once
- **WHEN** one sustained-distress episode is reported by both detectors
- **THEN** the repeat window holds one episode and repeated_distress is not labelled
