## ADDED Requirements

### Requirement: Cycle runner with pacing
The cognitive cycle SHALL run as an async loop that targets a configurable
processing rate (Hz). Each tick SHALL collect events, invoke Syneidesis,
optionally broadcast, and record latency. The cycle SHALL be startable,
pausable, resumable, and shutdownable through explicit API calls.

#### Scenario: Tick honors processing rate target
- **WHEN** the cycle is configured at 5 Hz (200 ms per tick) and ticks for
  one second under no load
- **THEN** the cycle completes between 4 and 6 ticks in that second

#### Scenario: Pause stops ticks until resume
- **WHEN** the cycle is running and `pause()` is awaited
- **THEN** no further ticks begin until `resume()` is awaited

#### Scenario: Shutdown drains and exits
- **WHEN** `shutdown()` is awaited
- **THEN** the run loop returns and any pending Soma latency events are
  flushed to the bus

### Requirement: Independent processing and experiential rates
The cycle SHALL support a processing rate and an experiential broadcast
rate as independent parameters. When the experiential rate is lower than
the processing rate, the cycle SHALL still tick at the processing rate but
SHALL only promote a fraction of snapshots to experiential broadcasts in
the ratio of experiential rate to processing rate.

#### Scenario: Half-rate experiential broadcasts
- **WHEN** processing rate is 10 Hz and experiential rate is 5 Hz, and the
  cycle runs for 100 ticks
- **THEN** between 45 and 55 ticks publish to `workspace.broadcast` with
  `is_experiential=True`

#### Scenario: Equal rates broadcast every tick
- **WHEN** processing rate equals experiential rate
- **THEN** every tick publishes an experiential broadcast

### Requirement: Graceful module absence
The cycle SHALL skip any registered module that has no new events on its
stream this tick. The cycle SHALL NOT block on any individual module's
read and SHALL continue running if a module raises during processing.

#### Scenario: Quiet module skipped silently
- **WHEN** module `chronos` has no new events since the last tick
- **THEN** the cycle's collected event set contains no entries from
  `chronos.out` and no error is raised

#### Scenario: Erroring module does not stop the cycle
- **WHEN** the bus raises for `bad_module.out` on a tick
- **THEN** the cycle increments a per-module error counter, emits a
  latency event with `error=True`, and proceeds with the next tick

### Requirement: Tick latency published as cycle output
On every tick the cycle SHALL publish a tick-latency event to its own
`cycle.out` stream (source `cycle`) containing `tick_index`,
`wall_duration_ms`, `target_duration_ms`, `slip_ms`, and a boolean
`is_experiential`. Soma subscribes to `cycle.out` like any other consumer.
The cycle SHALL claim source `syneidesis` only when calling
`bus.publish_workspace`.

#### Scenario: Slip recorded when tick overruns
- **WHEN** a tick takes 350 ms with a 200 ms target
- **THEN** the latency event has `slip_ms >= 150` and the next tick begins
  immediately rather than after a negative sleep

### Requirement: Cycle hooks for lifecycle integration
The cycle SHALL expose a hooks protocol allowing other modules to register
callbacks for `on_pause`, `on_resume`, and `on_shutdown`. Hooks SHALL be
awaited in registration order; a hook raising SHALL log a warning but
SHALL NOT prevent later hooks from running.

#### Scenario: Pause hook fires before pause completes
- **WHEN** a module registers an `on_pause` hook and the cycle's `pause()`
  is awaited
- **THEN** the hook callable is awaited before `pause()` returns
