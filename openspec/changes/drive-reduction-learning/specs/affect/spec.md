## ADDED Requirements

### Requirement: The affect state event carries each deficit's no-response value
Each `affect.state` event SHALL carry `drive_no_response`, mapping each deficit (boredom, social drive, restlessness) to the value it would have reached over the update interval just ended, from its value at the start of that interval, with the build input the credit rule uses for no response and without the relief channels the credit rule labels `own`. The field SHALL be content-free, no template SHALL render it, and the drive dynamics and the credit rule SHALL be unchanged.

#### Scenario: No response in the interval
- **WHEN** an update interval passes with no intent and no learning progress
- **THEN** each deficit's `drive_no_response` equals its actual value

#### Scenario: An intent relieves restlessness
- **WHEN** an intent relieves restlessness during the interval
- **THEN** restlessness's `drive_no_response` exceeds its actual value by the relief and the restlessness value itself is what it would have been without the new field
