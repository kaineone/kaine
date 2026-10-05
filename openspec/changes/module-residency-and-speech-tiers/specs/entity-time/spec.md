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
- **WHEN** two lockstep runs receive the same scripted inputs, and in one of them every model-backed call is delayed by a random wall-clock interval
- **THEN** their cognitive-cycle traces and workspace contents are identical, excluding wall-time fields

#### Scenario: Lockstep without deterministic mode is refused
- **WHEN** the cycle boots with `lockstep = true` and `deterministic = false`
- **THEN** boot refuses with a configuration error

#### Scenario: An unsupported module blocks lockstep
- **WHEN** lockstep is enabled and an enabled module has no lockstep support
- **THEN** boot refuses and names that module

#### Scenario: A stuck participant freezes, never kills
- **WHEN** a participant has not finished tick k within `lockstep_timeout_s`
- **THEN** the cycle is frozen, an incident names the module and tick, the run is marked inadmissible, and the entity keeps running state intact
