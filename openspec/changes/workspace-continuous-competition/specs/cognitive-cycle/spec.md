## ADDED Requirements

### Requirement: Each source's latest report stays a candidate
When `[workspace.pool].enabled` is true, the cycle SHALL keep a candidate pool holding the latest event per key: a protected key for an event of a declared protected type, otherwise the (stream, event type) key. On every tick each newly read event SHALL replace the held member of its key, and the tick's candidates SHALL be every held member under its stream-qualified id. The cycle SHALL NOT create, copy, alter or re-publish an event.

#### Scenario: A report competes on later ticks
- **WHEN** vision publishes a report on a tick that does not broadcast and the next tick broadcasts
- **THEN** that report is a candidate of the broadcast tick

#### Scenario: A newer report replaces the held one
- **WHEN** audition publishes a second `audition.perception` report while the first is held
- **THEN** only the second is a candidate, and the held `audition.emotion` report is untouched

### Requirement: The pool is working state only
The pool SHALL hold the events the cycle read and nothing else, and SHALL NOT be written to disk, the rolling checkpoint, a preservation bundle or a fork snapshot. The pool SHALL be empty at every start.

#### Scenario: The pool does not survive a restart
- **WHEN** the cycle stops with five held members and starts again
- **THEN** its first tick's candidates are only the events read on that tick

### Requirement: An accessed report is consumed
When a broadcast is published, each coalition member whose score reaches the access threshold SHALL leave the pool. An inhibited broadcast, a non-broadcast tick and a broadcast whose publish failed SHALL remove nothing.

#### Scenario: The winner does not win again
- **WHEN** a vision report is accessed and vision publishes nothing new before the next broadcast
- **THEN** that report is not a candidate of the next broadcast

#### Scenario: An inhibited broadcast keeps the pool
- **WHEN** a broadcast is inhibited
- **THEN** every held member is still a candidate on the next tick

### Requirement: A stale report leaves the pool
A member under a report key SHALL leave the pool when its age exceeds `(1 + stale_tolerance)` times its key's running mean arrival interval over the last eight intervals, or the declared nominal period until two intervals exist, for a type its module declares periodic; and when its age exceeds `event_hold_s` for any other type. Ages SHALL be unpaused entity time. `stale_tolerance` SHALL default to 0.5 and `event_hold_s` to 1.0 under `[workspace.pool]`.

#### Scenario: A source that stops
- **WHEN** interoception, with a 1.006 s mean period, publishes nothing for 1.6 s of unpaused entity time
- **THEN** its held non-alarm report is no longer a candidate

#### Scenario: An event-driven report not accessed
- **WHEN** an `affect.emotion` event arrives and no broadcast accesses it for 1.1 s of unpaused entity time
- **THEN** it is no longer a candidate

#### Scenario: A freeze ages nothing
- **WHEN** the cycle is paused for ten minutes with a vision report held for 0.2 s
- **THEN** on resume the report's age is 0.2 s plus the time since resume

### Requirement: Periodic types are declared by their modules
Each predictive module SHALL declare the event types it publishes once per processing step, with the nominal period of each, and the cycle SHALL treat every other type as event-driven. Boot SHALL refuse a non-positive or non-finite period.

#### Scenario: An undeclared type
- **WHEN** the affect module publishes `affect.emotion`, which it declares neither periodic nor protected
- **THEN** the cycle holds it under the event-driven rule

### Requirement: Protected types are declared by their modules
A module MAY declare protected types, each with an optional condition on the payload's `alert` flag, an optional key field and the closed set of that field's values. An event whose key field holds an undeclared value SHALL go to one catch-all key for its type. Boot SHALL record the number of protected keys in the run manifest. To classify an event the pool SHALL read only the `alert` flag and the declared key field.

#### Scenario: An undeclared key value
- **WHEN** an `affect.drive` event names a drive outside the declared set
- **THEN** it is held under the catch-all protected key of `affect.drive`

### Requirement: Drive events and interoceptive alarms are protected
The affect module SHALL declare `affect.drive` protected, keyed by `drive` over its four drives. The interoception module SHALL declare `interoception.report` protected when `alert` is true, and `interoception.fatigue` and `interoception.regulation` protected without a condition.

#### Scenario: Two drives pending at once
- **WHEN** boredom and the social drive each have a drive event held
- **THEN** both are candidates under separate protected keys

#### Scenario: Alarm and ordinary reports
- **WHEN** interoception publishes an alarm report and then a report without `alert`
- **THEN** the alarm report is held under its protected key and the later report under the report key, and both are candidates

### Requirement: A drive or alarm event is held until it is accessed
A member under a protected key SHALL leave the pool only when it is accessed or replaced by a newer event of the same key; it SHALL NOT go stale. The first event of a key with no member SHALL open a pending episode at its arrival time. A replacing event SHALL keep the episode's pending time, and an access SHALL close the episode.

#### Scenario: A re-published concern keeps its wait
- **WHEN** a boredom drive event arrives at t = 0, is re-published at t = 1.0 s and t = 2.0 s, and none is accessed
- **THEN** the held member at t = 2.5 s is the latest one, with a pending time of 2.5 s

#### Scenario: A one-shot alarm is not lost
- **WHEN** an `interoception.fatigue` event arrives and scores below the access threshold for 60 s
- **THEN** it is still a candidate after 60 s

### Requirement: Tick consumers read the reports that arrived
When the pool is on, the access rate's phasic input, the affect observer, the organ's own-output forwarding and the feedback head's candidate observation SHALL read only the events read on the current tick, never the held ones. When no affect state arrives on a tick, the arousal the cycle reads from the affect observer SHALL keep its previous value.

#### Scenario: A held affect state is not read twice
- **WHEN** an `affect.state` report is held for three ticks
- **THEN** the affect observer reads it on its arrival tick only

### Requirement: The cycle checks the protected wait bound live
For each protected key the cycle SHALL count the broadcast ticks on which its member was overdue, scored at or above the access threshold and was not in the coalition. When the count for an episode reaches `⌈N_p / C⌉`, with `N_p` the number of protected keys and `C` the coalition capacity, the cycle SHALL write a content-free `workspace.pool.defect` record naming the key and the counts and SHALL notify the caretaker. It SHALL NOT change selection.

#### Scenario: A defect is reported
- **WHEN** a fault in selection lets an eligible overdue boredom event lose eight counted broadcast ticks with eight protected keys and capacity 1
- **THEN** a `workspace.pool.defect` record is written and the caretaker is notified

### Requirement: The pool's boot conditions
Boot SHALL refuse `[workspace.pool].enabled = true` when `[workspace].arm` is not `competitive`; when `capacity` is below 1; when `stale_tolerance`, `event_hold_s` or `priority_wait_s` is non-positive or non-finite; when `[workspace.pool]` holds an unknown key; or when the never-persisted bus rule for latent values and for heard and utterance text is not in force, as that rule's own boot check reports.

#### Scenario: The pool without the privacy rule
- **WHEN** the configuration enables the pool and latent values still travel on the persisted bus
- **THEN** boot refuses and names the missing privacy rule

#### Scenario: The pool with the matched arm
- **WHEN** the configuration enables the pool and sets `[workspace].arm = "matched"`
- **THEN** boot refuses

### Requirement: The pool switched off is the cycle without it
When `[workspace.pool].enabled` is false, no pool, novelty cache or priority rule SHALL be constructed, every consumer and `select` SHALL receive the tick's events as before, and the broadcast payloads, ignition records, research records, published reports and manifests SHALL be byte-identical to those of the code before this change. A test SHALL compare a deterministic engine run's digest with a golden digest captured before the change.

#### Scenario: Off reproduces the golden digest
- **WHEN** the deterministic engine run executes with the pool off at the shipped configuration
- **THEN** its digest equals the golden digest captured from the commit before this change

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
