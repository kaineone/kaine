# Design — `maturation-gate-liveness`

## Delivery

Three pull requests, each leaving staging safe because `[developmental_stage].enabled`
ships false:

1. **Evidence and readouts** (tasks 1.x, 3.1): idempotent lived time and sleep counts, a
   durable training-pass count, typed and fresh readiness readouts.
2. **Womb, locus and embodiment** (tasks 2.x).
3. **Acknowledgement, Nexus and lineage** (tasks 3.2, 3.3).

## Lived time (C3)

`EntityClock.now()` returns subjective seconds as a float. The runner keeps a per-boot
baseline: the first tick of each boot records `now()` and adds nothing; every later tick
adds `max(0, now - last)` to `StageState.lived_seconds` and moves the baseline. Downtime
between boots never counts, and a frozen clock (scale 0) adds nothing.

## Sleep count (C2)

The runner reads `hypnos.sleep.completed` events from `hypnos.out` with the bus cursor
API, counting events whose source is `hypnos`, and persists the last scanned stream ID in
`StageState.hypnos_cursor`. A completion is counted exactly once across restarts and
crashes because counting resumes after the persisted cursor.

When the cursor is unset (a fresh gestation), the runner sets it to the stream's current
tail on its first tick and counts nothing before it. Redis streams outlive entities, so
starting from `0` could count sleeps from an earlier entity on the same bus. A sleep that
completes between boot and the first tick is missed, which delays birth rather than
hastening it. If stream trimming drops entries while the cycle is down, the same holds.

## Training passes (C2)

A new bus event is not used for Phantasia training passes: the cycle engine reads every
active module's `.out` stream as workspace candidates, so a "training completed" event
would enter the entity's global workspace as content that nothing in the neuroscience
calls for.

Instead the count lives with the learning it measures. Phantasia already restores learned
weights from its checkpoint when `persist_weights` is on. After each successful checkpoint
save it writes the cumulative pass count to a sidecar next to the checkpoint
(`<checkpoint>.passes.json`, atomic), and restores it when it loads the weights. The runner
reads `successful_training_passes` from the module, as today.

- With persisted weights, the count survives restarts together with the consolidation it
  counts.
- Without persisted weights, the world model restarts untrained each boot, and so does the
  count. Passes that no longer shape the model are not evidence of consolidation.
- A crash between the checkpoint write and the sidecar write undercounts by one pass,
  which delays birth.
- A preservation bundle carries the weights but not the sidecar, so a being revived from
  a bundle restarts its pass count at zero. That also only delays birth.

## Readiness readouts (C1)

`AsyncBus.latest(stream)` returns the newest decoded entry, and `AsyncBus.server_time_ms()`
returns Redis `TIME` in milliseconds. At start the runner records the boot time from Redis.
A readout counts only if its event type is `gestation.readiness`, its stream-ID timestamp is
at or after the boot time, and its age is at most
`readout_max_age_cadences × gate_cadence_seconds` (default 3 cadences). Stream IDs and
`TIME` come from the same Redis clock, so host clock skew does not matter.

## Who writes the stage file

Only the gate runner. Boot resolves the stage and no longer writes it; the runner writes
it on its first tick (anchoring gestation), whenever accumulated evidence changes, and at
birth.
