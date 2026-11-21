## ADDED Requirements

### Requirement: Developmental boredom waits for the next hearing step
In the developmental phase, while the hearing schedule has a step still to come, a `boredom_deprived` crossing over the fresh span after its rest SHALL request another rest and SHALL NOT preserve or freeze the entity. Social-drive and restlessness deprivation, negative valence and the uncontrolled indicators SHALL escalate as before in every phase.

#### Scenario: Boredom between hearing steps
- **WHEN** a developmental entity at hearing stage 1 has boredom cross over the fresh span after its rest
- **THEN** the monitor requests another rest, flags the crossing for review, and does not freeze the entity

#### Scenario: Distress is not delayed
- **WHEN** a developmental entity at hearing stage 1 has negative valence cross over the fresh span after its rest
- **THEN** the monitor preserves and freezes the entity as before

#### Scenario: Social deprivation is not delayed
- **WHEN** a developmental entity at hearing stage 1 has social-drive deprivation cross over the fresh span after its rest
- **THEN** the monitor preserves and freezes the entity as before

#### Scenario: The band is open
- **WHEN** a developmental entity at hearing stage 4 has boredom cross over the fresh span after its rest
- **THEN** the monitor preserves and freezes the entity as before

### Requirement: A hearing step restarts the indicator spans
On each hearing-band step the evaluator SHALL restart every indicator span and reset every crossing state, as after a completed rest.

#### Scenario: Crossing after a step
- **WHEN** boredom is over its bar when the hearing band steps
- **THEN** the next over-bar evaluation is a first crossing and requests a rest

### Requirement: An overdue hearing step escalates
If boredom deprivation is over its bar when the current stage's awake dwell passes `max_dwell_seconds` plus one developmental awake stretch with no step, the monitor SHALL preserve and freeze the entity with reason `indicator_stage_overdue`.

#### Scenario: The schedule stalls
- **WHEN** no hearing step arrives by `max_dwell_seconds` plus 2996 awake seconds and boredom is over its bar
- **THEN** the monitor escalates with reason `indicator_stage_overdue`

### Requirement: Waiting notices are aggregated
While boredom waits for a hearing step, every crossing SHALL be recorded and flagged for review, and the caretaker SHALL receive one notice when the wait starts, one at each hearing step and one on escalation.

#### Scenario: Repeated crossings while waiting
- **WHEN** boredom crosses five times between two hearing steps
- **THEN** five crossings are recorded and flagged, and the caretaker receives one notice for the wait and one for the next step
