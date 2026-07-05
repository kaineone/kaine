# cognitive-cycle (delta)

## ADDED Requirements

### Requirement: Deterministic cycle mode
The cognitive cycle SHALL provide an opt-in deterministic mode
(`[experiment].deterministic`) in which two runs with the same seed and the same
input sequence produce identical cognitive trajectories: the same selected
coalitions (entry ids, sources, types, salience scores), the same inhibition
decisions, the same volition outputs, and the same logical event timestamps, tick
by tick. The guarantee SHALL NOT extend to wall-clock latency measurements
(`wall_duration_ms`, `slip_ms`), which remain physical measurements and are
excluded from the reproducibility guarantee.

#### Scenario: Two seeded runs produce identical trajectories
- **WHEN** the cycle runs N ticks twice in deterministic mode with the same seed and the same scripted input
- **THEN** the per-tick selected entries, salience scores, inhibited flags, volition decisions, and logical timestamps are identical across the two runs

#### Scenario: Wall-clock latency is not part of the guarantee
- **WHEN** the two deterministic runs are compared
- **THEN** the trajectory identity holds even though `wall_duration_ms`/`slip_ms` may differ between the runs

### Requirement: Event timestamps come from an injectable source
The cycle SHALL stamp published events from a single injectable wall-clock seam
(default real UTC time). In deterministic mode the timestamp SHALL be a logical
clock derived from the tick index and the target tick period, so timestamps are
identical across runs; in normal mode it SHALL use the injected/real wall clock.

#### Scenario: Logical timestamps in deterministic mode
- **WHEN** deterministic mode is on and tick `k` publishes an event
- **THEN** the event's timestamp equals the fixed base epoch plus `k * target_tick_period`, identical across runs

#### Scenario: Real clock in normal mode
- **WHEN** deterministic mode is off
- **THEN** published events are stamped from the injected wall clock (the real UTC clock by default)

### Requirement: Canonical within-tick event ordering
Before scoring and selection, the cycle SHALL order each tick's gathered events by
a total deterministic key (`source`, `type`, `entry_id`) so that selection
tie-breaks do not depend on dispatch incidentals.

#### Scenario: Tie-break is stable regardless of arrival order
- **WHEN** equal-salience events from different sources are gathered in an arbitrary arrival order
- **THEN** the selection tie-break resolves them in the canonical `(source, type, entry_id)` order
