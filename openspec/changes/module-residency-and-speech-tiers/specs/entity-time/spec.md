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
`[cycle].lockstep = true` SHALL be accepted only with `deterministic = true`, and SHALL default to false.

In lockstep:
- every module event SHALL carry the tick that caused it (`tick`) and a per-module sequence number (`seq`);
- the engine SHALL wait after each tick until every participating module has finished that tick, meaning `on_workspace` has returned and every task it tracked for that tick has completed;
- intake SHALL read events with `tick` ≤ k, ordered by `(tick, source, seq)`;
- broadcast payloads SHALL carry logical entry ids and timestamps;
- the registry's shared `EntityClock` SHALL be driven by logical time;
- perception SHALL come from a seeded scripted feed advanced once per tick.

Boot SHALL refuse lockstep when any enabled module lacks lockstep support, naming the modules. A participant that has not finished within `[cycle].lockstep_timeout_s` SHALL freeze the cycle, record an incident naming the module and tick, and mark the run inadmissible. It SHALL never stop the entity.

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
In lockstep, Soma SHALL sample the real body once per tick. A scripted interoception source SHALL be refused at boot unless `[soma].scripted_interoception_operator_opt_in = true`, and the run identity SHALL record `interoception_source`. A generation started while handling tick k SHALL be due at tick `k + N`, where N is `[cycle].lockstep_speech_offset_ticks`, fixed before launch and recorded in the run identity. Its output SHALL be stamped `tick = k + N - 1`. The barrier SHALL wait for it only when the engine reaches tick `k + N - 1` and it has not finished. Plugin modules SHALL declare lockstep support, and boot's refusal SHALL name unsupported plugins.

#### Scenario: Thought continues while a reply is composed
- **WHEN** Lingua starts a generation at tick k and N is 20
- **THEN** ticks k+1 to k+19 complete without waiting for it, and its output enters the intake of tick k+20

#### Scenario: A scripted body is refused for a real entity
- **WHEN** a cycle boots with `[soma].interoception_source = "scripted"` and no operator opt-in
- **THEN** boot refuses with a configuration error

