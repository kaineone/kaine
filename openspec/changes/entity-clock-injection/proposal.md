## Why

The entity-time spec requires every timer that models cognition to run on the shared `EntityClock`, so that one `time_scale` dilates the whole mind coherently. A timing audit on 2026-09-26 found cognitive timers that still read the wall clock:

- Chronos's interval feature and time-since-interaction (`chronos/module.py`, `featurizer.py`), both defaulting to `time.time`;
- the Volition speak guard (`workspace/volition.py`) and the drive-policy fallback (`workspace/drive_policy.py`), on `time.monotonic`;
- Vox's prosody-mirroring decay (`vox/module.py`);
- Soma's cycle-latency sense, which compares the tick's **wall** duration with a fixed wall setpoint.

At `time_scale = 1.0`, the shipped default, this is invisible. At any other scale these timers run on real time while the rest of the mind runs on subjective time, so they fall out of step. Automatic dilation (`slip-driven-time-dilation`) would make that the normal case on slow hardware. The last one matters most: a dilated mind on slow hardware would still feel its cycle as too slow, and Soma would report stress, although subjectively nothing is late.

## What Changes

- Chronos, the Volition speak guard, the drive policy and Vox's mirroring decay take the `EntityClock` and derive their durations and "now" from it. Chronos becomes a clocked factory.
- Soma's cycle-latency feature compares the tick's **subjective** duration (wall duration × `time_scale`) with its setpoint.
- Wall-clock sites that protect infrastructure, or that track real media and real audio, stay on wall time and are classified in code comments. These include Vox's speaking gate, Audition's feed and STT timing, request timeouts, bus polls, heartbeats and record timestamps.
- Nous's EFE timeout stays a wall-clock compute budget. It bounds how long one decision may take on real hardware; it does not model cognition.
- At `time_scale = 1.0` every changed timer computes exactly what it does today.

## Capabilities

### New Capabilities
- (none)

### Modified Capabilities
- `entity-time`: the remaining cognitive timers are named and moved onto the entity clock; Soma's latency sense is subjective.

## Impact

- `kaine/modules/chronos/{module,featurizer}.py`, `kaine/workspace/{volition,drive_policy}.py`, `kaine/modules/vox/module.py`, `kaine/modules/soma/module.py`, `kaine/boot.py` (factory wiring).
- Tests that pin each timer's behaviour at scale 1.0 and at another scale.
- No change at the shipped `time_scale = 1.0`.
