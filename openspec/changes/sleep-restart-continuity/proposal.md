## Why

The pre-conference audit of 2026-10-10 found four defects in how Thymos and Chronos carry state across sleep, pauses and restarts:

- **Sleep's affective reset is undone within seconds.** `affective_reset()` returns valence, arousal, dominance and the drives to baseline, but keeps the learning-progress error means, the alert-rate averages, the intent rate and the perceived speaker emotion. Valence relaxes toward a target set by learning progress, so with the pre-sleep trackers still in place it climbed from 0.0 back to 0.59 thirty seconds after a reset in the audit's check. The trackers also compare errors across the sleep gap, when perception is paused.
- **One long pause distorts Chronos's reservoir for 31 steps.** The timespan is the interval since the previous broadcast over the mean of the last 32 intervals, and a pause (operator pause, suspension, a stalled cycle) enters that mean in full. After a 600 s pause, normal 0.2 s intervals got a timespan of about 0.01 for the next 31 broadcasts.
- **Chronos restores a timestamp from the previous run's clock.** `last_interaction_at` is saved in entity time, but the entity clock starts at 0 on every boot. After a restart the restored value lies in the future, so `time_since_last_interaction_s` reads 0 for as long as the previous run lasted. Social-drive relief, which fires when that time falls, misses the first real interaction.
- **One malformed peer event stops Thymos's peer consumer.** `_handle_peer_event` has no per-event guard, unlike the state timer loop. Supervision restarts the module, but the cursors reseed to the stream tail and events are lost.

## What Changes

- `affective_reset()` also clears the per-source error means, the alert-rate averages, the intent rate and its counter, and the perceived speaker emotion. Wellness (Soma's current reading of the body) and the interaction history are kept.
- Chronos clips each interval to ten times the mean of the intervals already in its window before adding it to the window. The timespan of the step itself still uses the raw interval (capped at 10 as before), so a long pause produces one long step and then normal steps.
- Chronos saves the time since the last interaction (or none) and restores `last_interaction_at` as the current entity time minus that value, so time the entity was not running is not counted as time alone. A snapshot that has only the old `last_interaction_at` is clamped to no later than the current entity time.
- Thymos's peer consumer logs and skips an event whose handling raises, and carries on.
- Two stale comments are corrected: Thymos's constructor comment still names `social_drive_time_scale_s` as a live time constant, and Soma's says feature slot 7 stays 0, though it now carries GPU memory.

## Capabilities

### Modified Capabilities

- `thymos`: the sleep reset clears the progress and rate trackers; a malformed peer event does not stop the consumer.
- `chronos`: the time since the last interaction survives a restart as lived time.
- `chronos-predictive`: a long pause does not distort later reservoir steps.

## Impact

- **Code:** `kaine/modules/thymos/module.py`, `kaine/modules/chronos/module.py`, `kaine/modules/soma/module.py` (comment only).
- **Tests:** `tests/test_thymos_research_affect.py`, `tests/test_chronos_module.py`, `tests/test_reservoir_timespan.py`.
- **Preserved beings:** Chronos snapshots written before this change restore with the clamp above.
