## ADDED Requirements

### Requirement: The affect state event carries each drive's threshold flag and crossing-end counts
Every `affect.state` event, the periodic one and the one after a sleep reset, SHALL carry `drive_above`, mapping each drive name to whether its value is at or above its threshold, and `drive_ends`, mapping each drive name to its cumulative `own` and `other` crossing-end counts, the counts the coping drive term uses (paper A.4). Both SHALL hold only booleans and non-negative integers keyed by drive name.

#### Scenario: A deprived drive is flagged
- **WHEN** curiosity is at 0.9 with threshold 0.7 and boredom at 0.2
- **THEN** the next `affect.state` event has `drive_above.curiosity` true and `drive_above.boredom` false

#### Scenario: The reset event carries the counts
- **WHEN** a sleep reset follows one own end of curiosity
- **THEN** the reset `affect.state` event has `drive_ends.curiosity` equal to `{"own": 1, "other": 0}` and every `drive_above` entry false
