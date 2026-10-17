## ADDED Requirements

### Requirement: Vision reports carry the change ratio
Every `vision.report` SHALL carry `normalised_change`, the change score divided by the running mean of change scores used by the change alert, or 0.0 when that mean is 0, with forward prediction on or off (paper A.2).

#### Scenario: A step change carries a large change ratio
- **WHEN** four identical frames are followed by an orthogonal frame
- **THEN** the fifth report's `normalised_change` equals its change score over the running mean of change scores and is at least the change alert factor

#### Scenario: The first report carries zero
- **WHEN** the first frame is processed
- **THEN** its report carries `normalised_change` 0.0
