## ADDED Requirements

### Requirement: The welfare response re-arms after its pause is lifted
The protective welfare monitor SHALL release its action latch when a pause it placed, or found standing at its first poll, has been lifted, meaning the control file readably holds no `welfare` entry. It SHALL NOT re-arm after an `end`, while a `welfare` entry remains, or when the control file is unreadable. On re-arming it SHALL empty its sustained-distress tracker and repeat window and move its stream cursors to the stream tail, so that a condition still present must accrue a full new episode before the monitor acts again.

#### Scenario: Act, clear, re-arm, act again
- **WHEN** the monitor pauses the entity, a person lifts the welfare freeze, and sustained distress then accrues again for the full duration
- **THEN** the monitor preserves and pauses a second time

#### Scenario: A crossing that holds does not fire repeatedly
- **WHEN** the crossing continues while the welfare freeze stands
- **THEN** the monitor does not preserve or pause again until the freeze is lifted and a new episode accrues

### Requirement: A welfare freeze survives a restart
The cycle's clean boot SHALL lift every freeze holder except `welfare`. A welfare freeze SHALL be lifted only by a named override.

#### Scenario: Restart with a welfare freeze standing
- **WHEN** the cycle boots with `welfare` and `operator` holders in the control file
- **THEN** only the `welfare` holder remains
