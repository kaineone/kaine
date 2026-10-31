## ADDED Requirements

### Requirement: Every research run ends with a welfare exposure record
At shutdown a research-mode cycle SHALL write `state/welfare/exposure.json`, atomically and with mode 0600: awake seconds; per deficit the deprivation share, uncontrolled share, open crossings and sleep-reset ends; the negative-valence share; curiosity's interest share; and per A.4 indicator its largest value, crossings, rests requested and freezes placed. It SHALL hold numbers and fixed labels only. A failed write SHALL be logged at error level.

#### Scenario: A viewing with one rest
- **WHEN** a research run's boredom indicator crossed once and the requested rest was followed by no second crossing
- **THEN** the exposure record shows one boredom crossing, one rest requested and no freeze

#### Scenario: The record is content-free
- **WHEN** the record is written
- **THEN** every value is a number, a boolean or a label from the fixed indicator and drive tables
