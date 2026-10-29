## ADDED Requirements

### Requirement: The affect welfare record gives sleep-reset ends and open crossings
For each deficit drive (`boredom`, `social_drive`, `restlessness`) the `affect_welfare` record SHALL carry `<drive>_sleep_reset_ends`, the crossings ended by the sleep reset since the observer started, counted from increases of the `drive_reset_ends` count in `affect.state` (the first value sets the baseline and a fall sets a new baseline without counting), and `<drive>_open_crossings`, 1 when the latest `drive_open` flag for the drive is true, 0 when it is false, and null before any flag (paper section 6.2). The existing keys and their values SHALL be unchanged; a sleep-reset end SHALL NOT enter the uncontrolled share.

#### Scenario: The tenth boot's boredom
- **WHEN** boredom's counts go from zero to 85 own ends, 8 other ends and 2 sleep-reset ends with no crossing open
- **THEN** the record gives `boredom_uncontrolled_share` 8/93, `boredom_sleep_reset_ends` 2 and `boredom_open_crossings` 0

#### Scenario: A crossing held open
- **WHEN** a boredom goal stalls and the latest state reports boredom's crossing open
- **THEN** `boredom_open_crossings` is 1
