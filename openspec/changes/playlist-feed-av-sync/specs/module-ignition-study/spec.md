## MODIFIED Requirements

### Requirement: Each viewing's ignitions are measured the same way and compared across lines and steps
The analysis SHALL compute, for every completed viewing, the broadcast rate over unpaused programme time, the broadcasts per film-minute, coalition size, each module's share of broadcasts, member salience by module, the inhibited share, picture-to-sound drift when recorded, and data-quality counts; and SHALL compare each step's main line against its control line and each step against the previous one. Picture-to-sound drift SHALL be measured only from records whose audio position is on the programme's item; records whose audio position is on another item SHALL be left out of the drift and counted in the data-quality counts as `audio_on_other_item`. Its report SHALL be content-free and SHALL state the study's limits: accumulated order, familiarity-only control, one entity per line, and expected nulls for faculties without an input channel.

#### Scenario: Paused time does not dilute the rate
- **WHEN** a viewing includes a sleep replay window during which the programme was paused
- **THEN** the broadcast rate is computed over unpaused programme time only

#### Scenario: A comparison without enough overlap
- **WHEN** two film-minute profiles share fewer than 30 bins
- **THEN** their correlation is reported as not computed rather than as a number

#### Scenario: A broadcast at a film boundary
- **WHEN** a record's programme position is at the start of the second film and its audio position is still at the end of the first
- **THEN** the record is left out of the picture-to-sound drift and counted as `audio_on_other_item`
