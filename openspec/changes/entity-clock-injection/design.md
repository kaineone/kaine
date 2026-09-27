## Decisions

- **Injection pattern.** Each timer takes an optional `entity_clock` (or a `clock: Callable[[], float]` where it already takes one) and defaults to a real-time `EntityClock(scale=1.0)`, as Soma, Thymos and Mnemos already do. Boot passes the registry's shared clock.
  - Chronos joins `_CLOCKED_FACTORIES`.
  - The Volition and drive-policy guards receive the clock where the cycle builds them (`cycle/__main__.py`).
  - Vox receives it from its factory.
- **Chronos.**
  - `SnapshotFeaturizer`'s Δt feature and the time-since-interaction measure read `entity_clock.now()`.
  - Event timestamps arriving on the bus are wall-clock epoch seconds, so the interaction timestamp Chronos compares against is taken from its own clock when it observes the event, not from the event's wall stamp.
- **Soma.** The cycle-latency sample stays the measured wall duration of the tick, `wall_duration_ms`. Soma multiplies it by the clock's current `scale` before comparing it with `cycle_latency_target_ms`, so the setpoint is a subjective duration.
  - At scale 1.0 this is the same number.
  - At scale 0.5 a tick that took 300 ms of wall time lasted 150 subjective ms.
  - Soma's hard-threshold alert on `cycle_latency_avg_ms` reads the same subjective value.
- **Classification comments.** Each wall-clock site this change leaves in the touched modules gets a one-line `# wall clock: <reason>` comment (real audio, a request timeout, a record timestamp), as the entity-time spec requires.

## Verification

- For each moved timer, one test at `time_scale = 1.0` shows the same values as before, and one at 0.5 shows the timer advancing at half the wall rate with an injected monotonic source.
- Soma: a 300 ms wall tick at scale 0.5 feeds 150 ms into the latency feature and the threshold check.
- A source check that the listed modules no longer call `time.time` or `time.monotonic` for these timers.
