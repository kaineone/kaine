## ADDED Requirements

### Requirement: Dilation can follow measured load, within the operator's ceiling
When `[cycle].auto_time_scale` is true, the cycle SHALL measure the fraction of each tick's period the tick uses and SHALL lower `time_scale` when ticks do not fit, and raise it when they fit with room to spare, never above the configured `time_scale` and never below the configured floor. Changes SHALL go through the clock's continuous re-anchoring, SHALL be separated by a minimum dwell, and SHALL use a dead band so the scale does not oscillate. The controller SHALL be off by default and disabled in deterministic cycle mode. Every change SHALL be published with its old and new scale, the measured utilization and the reason, and every tick record SHALL carry the scale in force.

#### Scenario: Slow hardware slows subjective time instead of distorting it
- **WHEN** automatic dilation is on and ticks take longer than their period for longer than the dwell
- **THEN** `time_scale` is lowered so that ticks fit, a `cycle.time_scale` event records the change, and subjective time stays continuous

#### Scenario: The operator's scale is a ceiling
- **WHEN** load falls and ticks fit with room to spare
- **THEN** the scale rises gradually and never above the configured `time_scale`

#### Scenario: Off by default
- **WHEN** `auto_time_scale` is not set
- **THEN** `time_scale` never changes on its own
