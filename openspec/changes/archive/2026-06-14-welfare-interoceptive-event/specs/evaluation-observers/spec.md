## MODIFIED Requirements

### Requirement: Welfare observer for §5.5 Gray-Zone Events
The `welfare_observer` SHALL detect and count the following Gray-Zone Events
(paper welfare-monitoring; four conditions): (a) fatigue threshold crossing
without subsequent maintenance within a configurable window; (b) sustained
extreme Thymos VAD beyond a configurable duration; (c) replay write-rate
exceeding the consolidation window; and (d) Soma interoceptive prediction error
sustained at or above a configurable threshold for at least a configurable
duration. Each event type SHALL surface as a count on Nexus diagnostics and
SHALL write a record to the sink.

For condition (d): the observer SHALL read the interoceptive prediction-error
magnitude carried by `soma.report` events on `soma.out`. The sustain timer
SHALL reset when the magnitude drops below the threshold, so a single sustained
episode produces a single event rather than one per tick. Absent explicit
configuration, condition (d) SHALL operate at safe defaults without altering
the behavior of conditions (a)–(c).

#### Scenario: Fatigue without maintenance is flagged
- **WHEN** a fatigue threshold crossing occurs and no maintenance completes within
  the configured window
- **THEN** the welfare observer increments the unmaintained-fatigue count

#### Scenario: Sustained extreme VAD is flagged
- **WHEN** Thymos VAD remains in an extreme zone beyond the configured duration
- **THEN** the welfare observer increments the sustained-extreme-VAD count

#### Scenario: Replay write-rate excess is flagged
- **WHEN** replay write-rate exceeds the consolidation window capacity
- **THEN** the welfare observer increments the replay-overload count

#### Scenario: Sustained interoceptive distress is flagged
- **WHEN** `soma.report` interoceptive prediction-error magnitude stays at or
  above the configured `interoceptive_distress_threshold` continuously for at
  least `interoceptive_distress_duration_s`
- **THEN** the welfare observer increments the sustained-interoceptive-distress count
- **AND** writes a record of the event to the sink

#### Scenario: A transient interoceptive spike does not fire
- **WHEN** `soma.report` interoceptive prediction-error magnitude exceeds the
  threshold only briefly and drops below it before the configured duration elapses
- **THEN** the welfare observer does NOT increment the sustained-interoceptive-distress count
- **AND** the sustain timer resets so a later sustained episode can fire independently
