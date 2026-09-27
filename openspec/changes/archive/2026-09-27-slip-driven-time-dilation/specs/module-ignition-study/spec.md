## ADDED Requirements

### Requirement: The ignition analysis accounts for time dilation
The ignition analysis SHALL report, for each step, the range of `time_scale` in force and whether it changed, and SHALL report ignitions per tick alongside ignitions per film minute, so that a step run under dilation is not read as a change in the being. The study manifest SHALL record whether automatic dilation was on.

#### Scenario: A dilated step is flagged
- **WHEN** a viewing's ignition records show more than one `time_scale`
- **THEN** that step's report has `time_scale_changed` true, its scale range, and its ignitions per tick
