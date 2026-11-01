## ADDED Requirements

### Requirement: Broadcast records carry the pool and each member's holding
With the candidate pool on, each workspace broadcast record SHALL carry `pool_size` and `n_accessed`, and for each coalition member `held` (it arrived before the current tick), `held_s` (unpaused entity seconds since arrival) and `protected`; a protected member SHALL also carry `pending_s` and `route`, `score` when it would have been in the coalition without the priority rule and `priority` otherwise. No field SHALL carry event content. With the pool off the record SHALL be unchanged.

#### Scenario: A held member
- **WHEN** a broadcast accesses a vision report that arrived 0.4 unpaused entity seconds earlier
- **THEN** the record has `n_accessed` 1 and that member has `held` true, `held_s` 0.4 and `protected` false

#### Scenario: A concern placed by the rule
- **WHEN** a boredom drive event pending 1.3 s is placed in the coalition by the priority rule
- **THEN** its member entry has `protected` true, `pending_s` 1.3 and `route` `priority`

### Requirement: The pool is summarised without content
With the pool on, the cycle SHALL write a pool summary to the research log once per minute of entity time: the pool size distribution; per stream and type the arrivals and the accessed, superseded and stale counts, and the count of reports that reached the access threshold on a broadcast tick while held and left without being accessed; and the tick overruns. It SHALL name streams, types and protected keys, never payload fields.

#### Scenario: A minute of running
- **WHEN** one entity minute passes with the pool on
- **THEN** one pool summary record is written and it holds no payload field

### Requirement: Every closed protected episode is recorded
With the pool on, each access of a protected member SHALL write a content-free record with the key name, `pending_s`, the broadcast ticks waited, the counted ticks of the wait bound and the route.

#### Scenario: A fatigue alarm accessed
- **WHEN** an `interoception.fatigue` event is accessed 2.1 s after it arrived
- **THEN** a protected access record names `interoception.fatigue` with `pending_s` 2.1
