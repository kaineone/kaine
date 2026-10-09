## Why

Two findings of the mathematics review of 2026-10-08 about Thymos's arousal, which sets the gain on the workspace competition and the pace of access.

- **The appraisal nudge depends on the broadcast rate.** On each broadcast Thymos adds `0.05 * max(0, novelty)` to arousal and `0.05 * pleasantness` to valence, while relaxation toward baseline is proportional to elapsed time. Higher arousal raises the access rate, which raises the number of nudges per second: a positive-feedback loop whose mean-field balance `lambda * x = 0.05 * omega * f(x)` pins arousal at its ceiling for any sustained novelty above `lambda (1 - a0) / (gamma f_p) = 0.07`. The same rate dependence makes valence's equilibrium scale with the broadcast rate.
- **The cycle reads arousal late.** Thymos publishes its state only after handling a broadcast, and checks its one-second interval only then, so the arousal the cycle holds (and the fovea size and access rate it sets) can be about 1.3 seconds old at rest, and perceptual alerts that raised arousal between broadcasts wait for the next broadcast to be seen.

## What Changes

- **Per-time appraisal.** Each broadcast's appraisal nudges (valence and arousal) are scaled by `min(4, dt / dt_ref)`, with `dt` the subjective time since Thymos's previous update and `dt_ref = appraisal_reference_interval_s` (default 0.3 s, the resting broadcast period). At the resting rate behaviour is unchanged; at higher rates the nudge per second stays the same, so the access rate no longer feeds back into arousal through the appraisal. The ceiling condition becomes `omega > lambda (1 - a0) / (gamma / dt_ref) = 0.21`, out of reach of ordinary coalitions.
- **State on a timer.** A background task updates Thymos (relaxation and drives) and publishes `thymos.state` every `publish_interval_s` of subjective time, independent of broadcasts, so the held arousal is at most one interval plus one tick old. Publication after a broadcast keeps the same interval check.

## Capabilities

### Modified Capabilities

- `thymos`: rate-invariant appraisal nudges and timer-driven state publication.

## Impact

- **Code:** `kaine/modules/thymos/module.py`; `kaine/boot/factories/thymos.py` and `config/kaine.toml` (`appraisal_reference_interval_s`).
- **Behaviour:** arousal no longer runs away through the access rate; `thymos.state` events now arrive about once a second even without broadcasts, and as workspace candidates they keep their baseline salience. The welfare observer that samples `thymos.state` sees a steady rate.
- **Docs:** `docs/09-modules/thymos.md`.
- **Paper:** Appendix A.4 (the appraisal update, the lag bound, the threshold).
