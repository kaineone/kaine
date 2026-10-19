## Why

The eighth test boot of 2026-10-18 restarted a developing entity on the same state tree. Two clocks lost continuity at that restart.

1. Stimulus time jumped back 76.1 s (3598.7 s to 3522.5 s). The stimulus source clock restarts each boot from the stage file's awake time (`lived_seconds`), but it runs in real time, sleep included, so a plain restart moves stimulus time backwards by the sleep and frozen time of every earlier boot. The entity re-hears and re-sees stimulus it already had, and with the same seed the maternal speech schedule repeats. Paper section 7 says the stimulus "alone continues through sleep, as for a fetus", and A.7 says what persists with the entity is checkpointed "so a restart neither resets nor repeats" it. The module's own docstring says the mother is external, so her timeline continues.
2. Awake time lost about 58 s at the same restart. The gate runner adds awake time only at its 60 s ticks, the first tick of a boot only anchors, and the shutdown path adds nothing, so the partial interval since the last tick is dropped on every restart. Awake time feeds the maturation gate (C3), the voice repertoire unlock and the colour ramp. A.7 counts awake time "summed over boots", checkpointed each entity minute and at shutdown.

## What Changes

- The stage file gains `stimulus_source_seconds`, the stimulus source clock's own elapsed time. The gate runner records it on every tick (sleep included, because the gate keeps ticking while asleep) and on the final write at shutdown, in the same write as `lived_seconds`.
- On boot the stimulus source clock resumes from `stimulus_source_seconds`. A stage without it (written before this change, or by a boot without the stimulus source) falls back to today's offset, the awake time. The colour ramp and the voice unlock still follow awake time.
- Downtime while the process is stopped does not advance the stimulus clock. The entity clock is frozen while the process is stopped, and the paper's continuity is about sleep, which the entity lives through; a process stop is not lived. The paper does not say otherwise.
- At shutdown the gate runner adds the awake time since its last tick and writes the stage, before any await, so a cancelled task still records it. The write is skipped when a tick would have been skipped (not developing, matured, boot not anchored, no stimulus feed), so it can never overwrite the maturation record. Each boot's first tick still only anchors, so downtime never counts, and a crash loses at most the time since the last tick but never counts any time twice.
- The run descriptor records the resumed stimulus offset beside the awake offset.

## Capabilities

### Modified Capabilities

- `developmental-stage`: awake time is also accrued at shutdown; the stage file carries the stimulus source time.
- `developmental-stimulus`: the stimulus source clock continues across restarts from its own persisted time.

## Impact

- `kaine/lifecycle/stage.py`, `kaine/lifecycle/gate_runner.py`, `kaine/boot/perception_feed.py`, `kaine/cycle/__main__.py` (hands the clock to the gate runner).
- Docs: `docs/06-operation/development.md`.
- Tests: new `tests/test_stimulus_clock_continuity.py` and `tests/test_gate_lived_time_shutdown.py`.
- Behaviour: a plain restart no longer repeats stimulus or drops awake time. A crash can still replay up to one gate cadence (60 s) of stimulus and drop up to one cadence of awake time, as before for awake time. With the stimulus source off, or staging disabled, nothing changes.
