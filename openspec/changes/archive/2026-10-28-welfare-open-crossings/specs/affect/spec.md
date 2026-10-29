## ADDED Requirements

### Requirement: The state event carries sleep-reset ends and open crossings
Each deficit drive SHALL count the crossings the sleep reset ends: when `DriveSet.reset_deficits()` resets a deficit whose crossing latch is set, its `reset_ends` count SHALL rise by one. Every `affect.state` payload, periodic or after a sleep reset, SHALL carry `drive_reset_ends`, each deficit's count, and `drive_open`, whether each deficit's latch is set. The counts SHALL persist in the snapshot under `drive_reset_ends`; a missing or malformed entry SHALL leave the count at 0. `drive_ends` SHALL keep its `own` and `other` keys only.

#### Scenario: A sleep reset ends an open crossing
- **WHEN** boredom has crossed its threshold and not fallen back, and the sleep reset runs
- **THEN** the reset `affect.state` carries `drive_reset_ends.boredom` 1 and `drive_open.boredom` false
