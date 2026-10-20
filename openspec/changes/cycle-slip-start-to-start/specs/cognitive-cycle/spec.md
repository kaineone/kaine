## MODIFIED Requirements

### Requirement: Tick latency published as cycle output
On every tick the cycle SHALL publish a tick-latency event to its own
`cycle.out` stream (source `cycle`) containing `tick_index`,
`wall_duration_ms`, `target_duration_ms`, `slip_ms`, and a boolean
`is_experiential`. The interoception module subscribes to `cycle.out` like any other consumer.
The cycle SHALL claim source `workspace` only when calling
`bus.publish_workspace`.

`slip_ms` SHALL be measured from tick start to tick start: the time from the previous tick's start to this tick's start, minus the previous tick's budget, and never below 0. The first tick and the first tick after a pause SHALL report 0. The measurement SHALL NOT change the pacing: the wait after a tick SHALL remain the tick's budget minus its own wall time.

#### Scenario: Slip recorded when tick overruns
- **WHEN** a tick takes 350 ms with a 200 ms target
- **THEN** the next tick's latency event has `slip_ms >= 150` and the next tick begins
  immediately rather than after a negative sleep

#### Scenario: Oversleep of the pacing wait is slip
- **WHEN** each tick body takes 1 ms against a 200 ms budget and every pacing wait of 199 ms overruns by 3 ms
- **THEN** every tick after the first reports `slip_ms` of about 3, and the cycle still requests waits of 199 ms

#### Scenario: A pause is not slip
- **WHEN** the cycle is paused for 10 s and resumed
- **THEN** the first tick after the resume reports `slip_ms` 0
