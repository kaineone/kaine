## MODIFIED Requirements

### Requirement: Each viewing's ignitions are measured the same way and compared across lines and steps
The analysis SHALL compute, for every completed viewing, the broadcast rate over unpaused programme time, the broadcasts per film-minute, the candidate pool size, the accessed share of broadcasts, each module's share of broadcasts, member salience and age by module, the inhibited share, picture-to-sound drift when recorded, and data-quality counts; and SHALL compare each step's main line against its control line and each step against the previous one. Its report SHALL be content-free and SHALL state the study's limits: accumulated order, familiarity-only control, one entity per line, and expected nulls for faculties without an input channel.

#### Scenario: Paused time does not dilute the rate
- **WHEN** a viewing includes a sleep replay window during which the programme was paused
- **THEN** the broadcast rate is computed over unpaused programme time only

#### Scenario: A comparison without enough overlap
- **WHEN** two film-minute profiles share fewer than 30 bins
- **THEN** their correlation is reported as not computed rather than as a number

#### Scenario: Pool size grows with the module set
- **WHEN** branch k adds a module that reports on a declared period
- **THEN** the viewing's mean pool size is reported and can be compared with branch 0's
