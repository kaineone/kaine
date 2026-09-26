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

## Womb before spawn and womb loss (tasks 2.1, 2.2)

Both checks use the womb-liveness interface from `local-womb-feed`
(`kaine/lifecycle/womb_liveness.py`) and nothing else, so a local womb and an external
provider are treated alike.

### Before spawn

When staging is enabled and the resolved stage is `gestation`, `_boot_and_run` holds
after the bus opens and before any module initializes. It calls `check_womb_ready`
every `womb_ready_retry_seconds` (default 5 s). Each failed check logs a warning and
publishes `stage.gestation.no_stimulus` on `lifecycle.out` with the check's reason. The
hold ends when the womb is ready, or at shutdown. While held, no module initializes and
the cycle does not start, so no entity runs, senseless or otherwise. This replaces
today's warn-and-continue path for a gestating entity without a womb.

### Womb loss

A `WombLossWatcher` (a cycle-layer task, `kaine/cycle/womb_watch.py`) runs while the
stage is `gestation` and stops at birth. Every `womb_check_seconds` (default 1 s) it
calls `check_womb_live`.

- **Arming.** A local womb publishes presence only once the senses are actually
  receiving it, which can take a while after boot (the vision encoder loads first). The
  watcher therefore arms on its first live observation. A womb that never becomes live
  within `arm_timeout_seconds` (default 120 s) is lost.
- **Grace.** Presence needs two advancing events inside the window, so after arming, and
  after each return, the watcher does not judge the womb for
  `window_s + 2 × womb_check_seconds`.
- **Hysteresis.** Loss is declared after `womb_loss_after_seconds` (default 5 s) of
  continuous not-live checks. Return is declared after two consecutive live checks.
  One missed event never freezes the entity.
- **On loss:**
  - `push_freeze(source="gestation", reason="womb lost")` on the existing freeze stack,
    so the freeze-watch loop pauses the cycle;
  - `stage.gestation.womb_lost` on `lifecycle.out` (salience 0.9);
  - a `log.critical`;
  - a content-free `womb_lost` caretaker notice when a caretaker is configured.

  The perception locus stays locked to the womb; nothing unlocks it to `physical`.
- **On return:** `pop_freeze(source="gestation")` and `stage.gestation.womb_returned`.
  The cycle resumes only when no other holder (operator, Spot, welfare) still has a
  freeze on the stack.
- **An operator unfreeze while the womb is still lost.** `unfreeze()` lifts every
  freeze, including the gestation entry. If the watcher still judges the womb lost, it
  pushes its freeze again on its next check and logs that it did. A gestating entity is
  never left running senseless.

### Why the freeze stack, not a stopped clock

The spec asks for the entity clock to pause. Setting `EntityClock.scale` to 0 at runtime
is not used: at scale 0, `EntityClock.sleep` returns immediately, so anything pacing on
it would spin. Instead, the pause is the existing freeze path under its own holder,
`gestation`, and lived time is kept honest by the next rule.

### Frozen time is not lived time

The cognitive cycle records the subjective time it spends paused (entity-clock seconds,
including a pause still in progress). Between two ticks, the gate runner adds the
entity-clock delta minus the paused time accumulated over the same span. The runner
ticks only every `gate_cadence_seconds`, so sampling a frozen flag at tick time would
still count a short freeze that fell between two ticks; subtracting the measured paused
time is exact. A frozen span is not experience, so it must not count toward C3 and
hasten birth. This applies to every freeze (operator, Spot, welfare, gestation), not
only womb loss.

### Perception during a womb-loss freeze

For other holders, the freeze-watch loop switches the desired perception flags off, so
nothing is sensed while suspended. For a freeze held only by `gestation` it leaves them
on. The loop reconciles this on every poll while paused, not only when the pause
begins. If another holder joins a gestation freeze, perception goes off. When the other
holders leave and only `gestation` remains, perception comes back, so the womb can
return. A local womb proves its return by delivering to the senses (the presence publisher
counts real deliveries), so switching perception off would make a local womb's return
impossible to observe, and the entity would stay frozen until an operator intervened.
The cycle is paused either way, so nothing is experienced. If any other holder is also
on the stack, perception goes off as usual.
