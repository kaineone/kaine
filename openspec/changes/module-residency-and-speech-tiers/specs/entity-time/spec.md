## ADDED Requirements

### Requirement: Automatic dilation sees stalled model-backed modules
Outside deterministic mode, the time-scale controller SHALL observe, per tick, the larger of the cycle's own utilization and a stall indicator. The indicator is 1.0 when an interactive-lane rung an enabled module depends on is `loading`, or a model-backed module's output is overdue by more than its calibrated load bound, and 0.0 otherwise. It SHALL pass through the existing EMA, hysteresis and dwell. With the residency manager passive, the controller's behaviour SHALL be unchanged.

#### Scenario: Sustained multiplexing lowers the time scale
- **WHEN** an interactive rung is `loading` on most ticks for longer than the controller's dwell
- **THEN** the controller lowers `time_scale` and publishes `cycle.time_scale` with the reason

#### Scenario: One short load does not change the scale
- **WHEN** a single load stalls ticks for less than the dwell
- **THEN** `time_scale` is unchanged

### Requirement: An opt-in lockstep barrier makes deterministic runs independent of wall time
`[cycle].lockstep = true` SHALL be accepted only with `deterministic = true` and SHALL default to false. In lockstep, the engine SHALL wait after each tick until every participating module has finished, events SHALL carry `tick` and `seq`, and intake SHALL order by `(tick, source, seq)`. The registry's `EntityClock` SHALL be driven by logical time and perception SHALL come from a seeded scripted feed advanced once per tick.

#### Scenario: A multiplexed run reproduces an all-resident run
- **WHEN** two lockstep runs receive the same scripted inputs and the same recorded interoception trace (a test-harness feed), and in one of them every model-backed call is delayed by a random wall-clock interval
- **THEN** their cognitive-cycle traces and workspace contents are identical, excluding wall-time fields

#### Scenario: Lockstep without deterministic mode is refused
- **WHEN** the cycle boots with `lockstep = true` and `deterministic = false`
- **THEN** boot refuses with a configuration error

#### Scenario: An unsupported module blocks lockstep
- **WHEN** lockstep is enabled and an enabled module has no lockstep support
- **THEN** boot refuses and names that module

#### Scenario: A stuck participant freezes, never kills
- **WHEN** a participant has not finished tick k within `lockstep_timeout_s`
- **THEN** the cycle is frozen with the operator-releasable freeze, an incident names the module and tick, the run is marked inadmissible, and the entity's state is intact

### Requirement: Lockstep keeps the real body and lets thought run while speech is prepared
In lockstep, interoception SHALL sample the real body once per tick. A generation started at tick k SHALL be due at tick `k + N` where N is `[cycle].lockstep_speech_offset_ticks`, fixed before launch. The barrier SHALL wait for it only when the engine reaches tick `k + N - 1` and it has not finished. Plugin modules SHALL declare lockstep support.

#### Scenario: Thought continues while a reply is composed
- **WHEN** the language module starts a generation at tick k and N is 20
- **THEN** ticks k+1 to k+19 complete without waiting for it, and its output enters the intake of tick k+20

#### Scenario: A scripted body is refused for a real entity
- **WHEN** a cycle boots with `[interoception].interoception_source = "scripted"` and no operator opt-in
- **THEN** boot refuses with a configuration error

