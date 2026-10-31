## ADDED Requirements

### Requirement: Each processor's latest report stays a candidate
The cycle SHALL keep a candidate pool holding the latest report per (stream, event type). On every tick each newly read event SHALL replace the held report of its key, and the tick's candidates SHALL be every held report under its stream-qualified id. The pool SHALL hold real reports only, each with its own publication time; the cycle SHALL NOT create, copy or re-publish an event.

#### Scenario: A report competes on later ticks
- **WHEN** vision publishes a report on a tick that does not broadcast and the next tick broadcasts
- **THEN** that report is a candidate of the broadcast tick

#### Scenario: A newer report replaces the held one
- **WHEN** audition publishes a second `audition.perception` report while the first is held
- **THEN** only the second is a candidate, and the held `audition.emotion` report is untouched

### Requirement: An accessed report is consumed
When a broadcast is published, each of its accessed members SHALL leave the pool. In the matched arm the drawn accessed members SHALL leave it, and in the pooled arm every member SHALL leave it. An inhibited broadcast, a non-broadcast tick and a broadcast whose publish failed SHALL remove nothing.

#### Scenario: The winner does not win again
- **WHEN** a vision report is accessed and vision publishes nothing new before the next broadcast
- **THEN** that report is not a candidate of the next broadcast

#### Scenario: An inhibited broadcast keeps the pool
- **WHEN** a broadcast is inhibited
- **THEN** every held report is still a candidate on the next tick

### Requirement: A stale periodic report leaves the pool
A report of a type its module declares periodic SHALL leave the pool once its age in entity time exceeds `(1 + stale_tolerance)` times its source's running mean report period, the mean over the last eight intervals of that key, or the module's declared nominal period until two intervals exist. `stale_tolerance` SHALL default to 0.5 under `[workspace.pool]`.

#### Scenario: A source that stops
- **WHEN** interoception, with a 1.006 s mean period, publishes nothing for 1.6 s of entity time
- **THEN** its held report is no longer a candidate

### Requirement: Periodic report types are declared by their modules
Each predictive module SHALL declare which of its event types it publishes once per processing step, with the nominal period of each. The cycle SHALL treat every other type as event-driven. A declared type with a non-positive or non-finite period SHALL be refused at boot.

#### Scenario: An undeclared type
- **WHEN** the affect module publishes `affect.drive`, which it does not declare periodic
- **THEN** the cycle holds it under the event-driven rule

### Requirement: An event-driven report is held for a fixed span
A report of an event-driven type SHALL leave the pool when superseded, accessed, or after `event_hold_intervals` resting access intervals of entity time, default 3 under `[workspace.pool]`.

#### Scenario: A drive event not accessed
- **WHEN** a drive event arrives and no broadcast accesses it for 1 s of entity time at a resting access rate of 3.33 Hz
- **THEN** it is no longer a candidate

### Requirement: Tick consumers read the reports that arrived
The affect observer, the cycle's arousal estimate, the organ's own-output forwarding and the feedback head's candidate observation SHALL read only the events read on the current tick, never the held ones. When no affect state arrives on a tick, the arousal estimate SHALL keep its previous value.

#### Scenario: A held affect state is not read twice
- **WHEN** an `affect.state` report is held for three ticks
- **THEN** the affect observer and the arousal estimate read it on its arrival tick only

## MODIFIED Requirements

### Requirement: The access rate's phasic input counts alerts only
The phasic input to the access rate SHALL be computed from the highest intensity among the module reports that arrived on the tick and whose payload has `alert` true; reports without it SHALL NOT count, and a held report SHALL NOT count again on a later tick, so with no newly arrived alert the access rate rests at its resting value.

#### Scenario: A graded report does not raise the rate
- **WHEN** a tick's only module report has intensity 0.6 and no alert flag, at baseline arousal
- **THEN** the phasic input is 0 and the access rate is the resting rate

#### Scenario: An alert raises the rate
- **WHEN** a tick's newly arrived module reports include one with intensity 0.8 and `alert` true
- **THEN** the phasic input is greater than 0

#### Scenario: A held alert counts once
- **WHEN** an alert report arrives on one tick and stays held for the next four ticks with no new alert
- **THEN** the phasic input is greater than 0 on the arrival tick only
