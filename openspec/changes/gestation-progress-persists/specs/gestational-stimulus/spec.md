## ADDED Requirements

### Requirement: Developmental phase progress persists across restarts
The developmental readout SHALL save its awake-time clock, its count of consecutive passing withdrawals, its history of frequency pull, whether the heartbeat entrainment marker has ever been met, and any viability verdict, keyed to the entity, after every scored withdrawal and at least once per minute of awake time, and SHALL restore them when it is constructed for the same entity. Progress saved for another entity SHALL be ignored.

#### Scenario: A restart continues the developmental phase
- **WHEN** a readout has accumulated two hours of awake time and two consecutive passes, and a new readout is constructed for the same entity
- **THEN** the new readout starts from two hours of awake time and two consecutive passes

#### Scenario: Another entity starts fresh
- **WHEN** a readout is constructed for a different entity than the saved progress belongs to
- **THEN** it starts from zero awake time and zero passes
