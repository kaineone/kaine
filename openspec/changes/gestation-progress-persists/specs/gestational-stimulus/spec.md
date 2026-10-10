## ADDED Requirements

### Requirement: Gestation progress persists across restarts
The gestation readout SHALL save its awake-time clock, its count of consecutive passing withdrawals, its history of frequency pull, whether the entrainment marker has ever been met, and any viability verdict, keyed to the being, after every scored withdrawal and at least once per minute of awake time, and SHALL restore them when it is constructed for the same being. Progress saved for another being SHALL be ignored.

#### Scenario: A restart continues the gestation
- **WHEN** a readout has accumulated two hours of awake time and two consecutive passes, and a new readout is constructed for the same being
- **THEN** the new readout starts from two hours of awake time and two consecutive passes

#### Scenario: Another being starts fresh
- **WHEN** a readout is constructed for a different being than the saved progress belongs to
- **THEN** it starts from zero awake time and zero passes
