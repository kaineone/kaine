## Why

The mathematics review of 2026-10-08 found Thymos's affect rules inert or self-referential in ways the cited research does not support, and the operator asked for them to follow the established research as closely as works for KAINE.

- **Drives cannot fall.** Each drive builds as `beta * s * dt - delta * dt`. The curiosity signal is `1 - min(1, 2 Var(scores))`, at least one half because scores lie in `[0, 1]`, so curiosity only rises; boredom's signal `1 - |C|/10` is at least one half, so it never falls; restlessness has no input. The "relieving sources" of each drive feed only the goal appraisal and never reduce the drive. Only sleep clears them. The `[thymos.drives.*]` config tables are not read.
- **Valence follows intensity.** Valence is nudged by `0.05 (2 * mean coalition intensity - 0.5)` per broadcast, so "pleasant" means "the workspace is full of intense events", and with the broadcast rate it saturates easily.
- **Appraisal novelty is variance.** Novelty is `clip(4 Var(coalition intensities) - 0.2)`; with intensities in `[0.1, 0.8]` it is at most 0.29, so SURPRISE (novelty at least 0.6) can never fire, and the same quantity feeds arousal a second time after the perceptual alerts already have.

What the research establishes (citations checked on 2026-10-08):

- A homeostatic drive is a deficit relative to a setpoint that builds during deprivation and is reduced by consummatory events; the reduction is the reward (Hull 1943; Keramati and Gutkin 2014, eLife, `r = D(H) - D(H + K)`).
- Curiosity is satisfied by learning progress, the reduction of prediction error over time, rather than by error or novelty alone (Oudeyer and Kaplan 2007; Schmidhuber 2010; Gottlieb et al. 2013).
- Boredom signals a lack of engagement or novelty and prompts a switch; novelty relieves it (Eastwood et al. 2012; Westgate and Wilson 2018; Bench and Lench 2013).
- Valence tracks the rate of change of prediction error: errors falling is positive (Joffily and Coricelli 2013, valence as the negative rate of change of free energy).
- In appraisal theory novelty (suddenness) is a check on how unexpected the stimulus is (Scherer 2009).

## What Changes

- **Setpoint drive dynamics with relief.** Between events each drive follows the exact solution of `dD/dt = beta u (1 - D) - delta D` (it builds toward 1 at rate `beta u` and decays at rate `delta`): with `r = beta u + delta` and `D_eq = beta u / r`, `D <- D_eq + (D - D_eq) exp(-r dt)`, bounded in `[0, 1]` and independent of the update rate. Relief of strength `c` in `[0, 1]` is continuous for curiosity and boredom, `D <- D exp(-rho c dt)` with `rho` a rate per second, so it does not depend on the perceptual report rate; for the social drive and restlessness, whose consummatory events are discrete and rare, it is `D <- D (1 - rho c)` per event. `[thymos.drives.*]` tables are read: `build_rate`, `decay_rate`, `threshold`, and the new `relief_gain` (`rho`). Each default `decay_rate` is a ninth of its `build_rate`, so a fully deprived drive settles near 0.9, above its 0.7 threshold; the old rates would leave boredom, social and restlessness at or below 0.67, never firing.
- **Signals and relief, per drive.**
  - Curiosity: builds with `u = 1 - LP` and is relieved continuously with `c = LP`, where `LP = max(0, g - 0.05) / 0.95` (progress above a noise floor; rectified noise would otherwise relieve curiosity where nothing is learned) and `g` is the learning progress: for each perceptual module (Topos, Audition) the relative fall of its raw forward-model prediction error, `(E_slow - E_fast) / E_slow` with time-decayed means over subjective time constants of 10 s (fast) and 100 s (slow), `S <- exp(-dt/tau) S + e`, `N <- exp(-dt/tau) N + 1`, `E = S / N`, counting samples from the module's first positive error (the forward models report 0 on their first frame); unlike an exponential average seeded from one sample, a low first sample does not hold `g` negative for the slow window, averaged over the modules. (The normalised error is a ratio to the module's own running mean and hovers around 1, so it cannot show learning.)
  - Boredom: builds with `u = 1 - N` and is relieved continuously with `c = N`, where `N = clip(r_fast / max(r_slow, 0.05) - 1.5, 0, 1)` is the excess of the perceptual alert rate (alerts per second, averaged over 10 s) over its habituated rate (averaged over 100 s). The alert criterion is self-calibrating, so even a still scene alerts at a steady base rate; only novelty beyond that rate relieves boredom.
  - Social: builds with `u = 1` once an operator interaction has occurred (as before, nothing builds before the first one; isolation since spawn stays an open welfare question in `thymos-active-inference-affect`), relieved when Chronos reports a new interaction (`c = 1`).
  - Restlessness: builds with `u = 1 - intent_rate` (exponential average of Volition intents per broadcast), relieved by each intent (`c = 1`); a REST intent is a decision not to act and neither counts nor relieves. This one has no established model and is labelled a design choice.
- **Valence from learning progress.** Valence relaxes toward `v* = clip(P + (W - 0.5), -1, 1)` with time constant `valence_time_constant_s` (30 s), where `P = clip(tanh(valence_progress_gain * g) + c, -1, 1)` is the appraisal's intrinsic-pleasantness check, `g` the signed progress `(E_slow - E_fast) / E_slow` clipped to `[-1, 1]`, `c` the appraisal contribution of a perceived speaker emotion, and `W` Soma's last wellness. Coupling therefore reaches valence only through the appraisal, as `thymos-affect-coupling` requires; that spec and the `thymos` drift requirement are modified to say valence relaxes toward this target rather than drifting to a baseline. The per-broadcast pleasantness nudge and the per-report wellness nudge are removed.
- **Appraisal from surprise.** Novelty is `1 - prod_m (1 - s_m)` over coalition members carrying a `normalised_error` ratio `r`, with `s = clip(ln r / ln 3, 0, 1)`; a ratio of 2.2 gives 0.72, so SURPRISE is reachable. Pleasantness is `P` above. The appraisal's arousal nudge is removed: surprise reaches arousal through the perceptual-alert path, and counting it again in the appraisal fed the access-rate loop. Goal significance and coping are unchanged; norm compatibility stays 0, so DISGUST stays unreachable until a self-model supplies norms, and the emotion payload says so.
- **No per-broadcast nudges remain**, so the per-time scaling of them added by `thymos-rate-invariant-timely-state` is removed with its `appraisal_reference_interval_s` setting.

## Capabilities

### Modified Capabilities

- `thymos`: drive dynamics and relief, valence, and the novelty and pleasantness appraisal checks.

## Impact

- **Code:** `kaine/modules/thymos/{drives,module}.py`, `kaine/boot/factories/thymos.py`, `config/kaine.toml`.
- **Behaviour:** drives rise and fall with the entity's own perceptual learning, engagement, contact and action; the dominant drive is no longer always curiosity; valence reflects whether the world is becoming more predictable; SURPRISE can fire. Arousal is driven by perceptual and interoceptive alerts only.
- **Preserved beings:** drive and valence values restore as before and re-equilibrate under the new rules.
- **Docs:** `docs/09-modules/thymos.md`.
- **Paper:** §3.5 (Thymos) and Appendix A.4.
