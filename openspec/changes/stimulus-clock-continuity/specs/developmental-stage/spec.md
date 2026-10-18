## MODIFIED Requirements

### Requirement: Developmental evidence accumulates idempotently across restarts
The gate runner SHALL record lived subjective time by adding the entity-clock delta between
its own ticks, using each boot's first tick only to set a baseline, so downtime never counts
as lived time. When it stops, it SHALL add the delta since its last tick and persist the stage
before any further await, whenever a tick would have run then, so a clean restart loses no
awake time and a crash never counts any span twice. It SHALL count the sleep module's maintenance cycles from their durable
`sleep.sleep.completed` events, remembering the last stream ID consumed, so a completion is
counted exactly once regardless of restarts or crashes; a fresh developmental phase SHALL start
counting from the stream's tail, never from sleeps that predate it. The world model module SHALL persist
its cumulative training-pass count beside its world-model checkpoint and restore it with the
weights, so the count survives exactly when the consolidation it measures survives; no new
bus event SHALL carry training passes, because module output streams are workspace
candidates. Evidence SHALL be persisted in the stage file by the gate runner only.

#### Scenario: Restart mid-development
- **WHEN** an entity in its developmental phase has accumulated 3 hours of subjective time and two completed
  sleeps, and the cycle restarts
- **THEN** after restart the gate reports at least 3 hours lived and exactly two sleeps

#### Scenario: A sleep completes just before a crash
- **WHEN** a sleep module cycle completes and the process crashes before the next gate tick
- **THEN** after restart that sleep is counted once

#### Scenario: Training passes follow the weights
- **WHEN** the world model module has completed four training passes with weight persistence on, and the
  cycle restarts
- **THEN** after restart the world model module reports four passes; with weight persistence off it
  reports zero

#### Scenario: Sleeps from before the developmental phase are not counted
- **WHEN** `sleep.out` already holds `sleep.sleep.completed` events when a fresh developmental phase
  begins
- **THEN** none of them is counted

#### Scenario: Downtime is not lived time
- **WHEN** the host is down for 12 hours between two boots
- **THEN** the lived-time total does not increase by those 12 hours

#### Scenario: A clean restart loses no awake time
- **WHEN** a developing entity has been awake 45 s since the gate's last tick and the cycle shuts down cleanly
- **THEN** the stage file holds those 45 s, and after restart the gate's first tick adds nothing

#### Scenario: A crash never double counts
- **WHEN** the process crashes 45 s after a gate tick and restarts
- **THEN** the stage file holds the awake time up to that tick, and no span is counted twice

#### Scenario: No shutdown write after maturation
- **WHEN** the entity has matured and the gate runner stops
- **THEN** the gate runner does not write the stage file again
