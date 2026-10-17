## Why

The paper's §3.5 "Emotion regulation" paragraph (predictive-workspace-paper #47) specifies a three-tier regulation monitor modeled on Gross's (1998) process model: attentional deployment, reappraisal and a sleep request, escalating on the episode, window and tier rule of A.5 while affect is intense and the appraisal negative. The code's `PassiveDecay` policy returns a zero adjustment on every update, and §5.4 lists emotion regulation as specified and not yet built. Tier 1 is the one place affect enters selection, so it must be logged and held at neutral in every arm of the workspace-mediation study (§6.3), where the A.1 ranking invariant assumes "no regulation bias".

## What Changes

- **Monitor.** A new `ThreeTierRegulation` policy in `kaine/modules/affect/regulation.py`. At every affect update the intensity is `max(|v|, a - a0)` and the appraisal is negative when the last appraisal's pleasantness or goal score is below 0. An episode runs from the first update with intensity at or above `set_point` (θ_E, 0.5) and a negative appraisal to the first update without both. After `Δst` entity seconds of an episode, each increase of `floor(Δst / sustain_window_s) >= 1` fires one activation of tier `min(floor(Δst / sustain_window_s), 3)`, the A.5 rule; `sustain_window_s` defaults to A.5's Δ_R (30 entity s), since Table A1 gives emotion regulation no window of its own.
- **Tier 1, attentional deployment.** During an episode the monitor sums, per source, the intensity of the members of each negatively appraised coalition. At tier 1 it publishes `affect.regulation` with the source of largest mass (ties to the alphabetically first), `bias` b_E (0.2) and `decay_s` τ_E (20 entity s). The workspace multiplies every candidate score `S'` of that source by `1 - b`, with `b = b_E exp(-(t - t1) / τ_E)` from the time `t1` the cycle collects the event, and writes the factor into the broadcast metadata. With no negatively appraised member in the episode the activation is logged with no source and no bias.
- **Tier 2, reappraisal.** Once per episode the module re-runs the appraisal of the last broadcast against the current coping and goal state and replaces the categorical emotion with its result (the paper's corrected §3.5: the emotion is what appraisal sets), publishing `affect.emotion` with `reappraised: true` when it changes. No dimension of the affective state moves.
- **Tier 3, sleep request.** The module publishes `affect.regulation` with `action: "request_maintenance"`. The sleep module's maintenance consumer, which already starts a sleep on the interoception module's `request_maintenance` advisory, also reads `affect.out` for this request, under the same guards. The affective reset at the end of that sleep is the backstop.
- **Logging.** Every activation publishes `affect.regulation` with its tier, action, intensity, episode time and `size` (tier 1: the bias applied; tier 2: 1 if the emotion changed, else 0, with `emotion_before` and `emotion_after`; tier 3: the intensity at the request) and is logged at info level.
- **Developmental phase.** Regulation is off while the entity is in its developmental phase and starts at maturation with tier 1, the escalation's first step. The cycle injects a probe (`stage.is_developing` when staging is enabled) through a wiring helper that a supervisor rebuild re-runs. With no probe (staging disabled, so the entity counts as matured) regulation runs.
- **Selection invariant in the study.** `[workspace].regulation_bias` (default `true`) gates the tier-1 multiplier. Every `config/studies/workspace_mediation_*.toml` sets it to `false`, so in every arm the scores carry no regulation bias and the A.1 ranking by `I × N` holds.
- **Off arm.** `[affect.regulation].policy` selects `"three_tier"` (shipped) or `"passive"`, which keeps the old `PassiveDecay` no-op and leaves the module bit-for-bit as before this change.
- **Config.** `[affect.regulation]`: `policy`, `set_point = 0.5`, `selection_bias = 0.2`, `bias_decay_s = 20.0`, `sustain_window_s = 30.0` (Table A1's θ_E, b_E, τ_E; A.5's Δ_R).

## Capabilities

### Modified Capabilities

- `affect`: a three-tier emotion-regulation monitor replaces the passive no-op, off during the developmental phase.
- `workspace`: tier 1 of emotion regulation multiplies one source's scores by a decaying factor, gated by `[workspace].regulation_bias` and off in every study arm.

## Impact

- `kaine/modules/affect/regulation.py`, `kaine/modules/affect/module.py`, `kaine/boot/factories/affect.py`, `kaine/boot/wiring.py`, `kaine/boot/registry.py`, `kaine/cycle/__main__.py`, new `kaine/workspace/regulation_bias.py`, `kaine/workspace/core.py`, `kaine/modules/sleep/module.py`, `config/kaine.toml`, `config/studies/workspace_mediation_*.toml`, docs for the affect, sleep and workspace pages and the configuration reference, new tests.
- Behaviour: with the shipped config a matured entity whose affect stays intense and negative for 30 entity seconds gets a decaying attentional bias against the source dominating its negative content, then one reappraisal, then sleep requests. Study runs keep selection unbiased. `policy = "passive"` restores today's behaviour.
