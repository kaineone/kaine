
## ADDED Requirements

### Requirement: A welfare-protective pause survives supervisor recovery

The system SHALL stack freeze sources such that a module-supervisor (Spot)
recovery removes only the supervisor's own freeze entry and SHALL leave any
welfare-protective pause standing with its original source and reason intact.
The system SHALL permit a welfare freeze entry to be lifted only by an operator
stand-down or an explicit welfare stand-down; no other actor — including Spot's
recovery path — SHALL lift it, and the experiential cycle SHALL remain paused
(resumed only when the freeze stack empties).

#### Scenario: Spot freezes over a welfare pause and recovery leaves the welfare pause standing

- **WHEN** the welfare monitor has taken a protective pause (a welfare freeze
  entry is active) and a module fault causes Spot to stack its own freeze on
  top, and the faulted module then recovers
- **THEN** Spot removes only its own freeze entry, the cycle remains frozen,
  and the welfare freeze entry remains with its original source and reason
  intact (the entity is not resumed)

#### Scenario: Only the operator or an explicit welfare stand-down lifts the welfare pause

- **WHEN** a welfare freeze entry is active and any actor other than the
  operator or an explicit welfare stand-down (including Spot's recovery path)
  attempts to lift the freeze
- **THEN** the welfare freeze entry SHALL NOT be removed and the cycle SHALL
  remain frozen until an operator stand-down or an explicit welfare stand-down
  occurs
