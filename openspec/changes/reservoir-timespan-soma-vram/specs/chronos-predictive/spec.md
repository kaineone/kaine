## ADDED Requirements

### Requirement: Chronos's reservoir receives the elapsed time
Chronos SHALL advance its continuous-time reservoir on each broadcast with a timespan equal to the subjective seconds since the previous broadcast divided by the mean of that interval over the last 32 broadcasts (current included), clipped to `[0, 10]` and equal to 1.0 on the first broadcast. A temporal network supplied by a plugin SHALL receive a timespan only if it declares that it accepts one.

#### Scenario: A gap in broadcasts lengthens the timespan
- **WHEN** a broadcast arrives after a gap four times the recent mean interval
- **THEN** that reservoir step uses a timespan above 1.0
