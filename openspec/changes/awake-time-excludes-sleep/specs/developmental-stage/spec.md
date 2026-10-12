## ADDED Requirements

### Requirement: Awake time excludes sleep and freezes
Every rule that reads awake time (the maturation gate's minimum, the individuation ledger, the developmental-phase readout's viability hours and the stimulus source's colour schedule) SHALL count only entity time during which the cycle is neither frozen nor in a sleep. Time that is both frozen and asleep SHALL be excluded once.

#### Scenario: Sleep does not count
- **WHEN** the entity sleeps for 600 entity seconds and is awake for 400
- **THEN** awake time grows by 400 seconds

#### Scenario: A freeze during sleep is excluded once
- **WHEN** the cycle is frozen for 100 seconds in the middle of a 600-second sleep
- **THEN** the time not awake grows by 600 seconds
