## Why

The paper calls the workspace a precision-weighted competition with arousal as its precision term, but the selection score does not implement precision. Every candidate's score is `I * N * G * T`, with `T = 0.2 + 0.8a` the same for every candidate on a tick. A common multiplier cannot change which candidate wins; it only moves the scores against the threshold and the report bars. The mathematics review of 2026-10-08 found this, and the operator asked for the selection rule to match established neuroscience as closely as possible.

What the literature establishes (citations checked against the sources on 2026-10-08):

- **Precision is per channel.** In predictive coding, the precision of a channel is the inverse variance of its prediction error, and attention weights each channel's errors by their precision (Feldman and Friston 2010, "inverse variance is called precision"; attention as synaptic gain). Channels whose errors are noisy count for less, so precision changes which signal wins.
- **Arousal acts as gain that sharpens contrast.** In adaptive gain theory, locus coeruleus noradrenaline steepens the slope of a unit's input-output function (Aston-Jones and Cohen 2005; Eldar, Cohen and Niv 2013, "high gain narrows attention"). Arousal-biased competition and the GANE model describe the result: arousal amplifies high-priority representations and suppresses low-priority ones (Mather and Sutherland 2011; Mather et al. 2016). These effects sharpen an existing competition rather than choosing a different winner.

## What Changes

- **Per-source precision.** Syneidesis keeps, for each event source, an exponential running mean and variance of the intensities that source publishes (one update per candidate, weight `precision_sample_weight`, default 0.02, about 50 events). The source's precision is `1 / (v + v0)`, with `v0 = 1e-4`. Its weight is `P = sqrt(pi / pi_ref)`, with `pi_ref` the geometric mean of the precisions of all warmed sources, clipped to `precision_bounds` (default `[0.5, 1.5]`). The weight is 1.0 for every source until at least three sources have `precision_warmup_samples` (default 20) events. A source whose surprise signal alerts habitually has a high variance and a weight below 1; a source whose alerts are rare and informative has a weight above 1. Each candidate's weight is computed from the statistics before its own update. The priority is `p = clip(I * N * G * P)`, and precision is what can now change the ranking.
- **Arousal contrast.** The arousal factor keeps its level effect `T(a) = 0.2 + 0.8a` and adds adaptive gain: the score is `S = T(a) * C_g(p)`, where `C_g` is the logistic `sigmoid(g (p - 0.5))` rescaled to map 0 to 0 and 1 to 1, and `g = arousal_contrast_gain * clip((a - a0) / (1 - a0), 0, 1)` with `a0` the baseline arousal. At or below baseline arousal `g = 0` and `C_g(p) = p`, so the score is exactly the previous one times `P`. Above baseline, priorities above one half are amplified and those below suppressed. `C_g` is monotone, so arousal changes contrast and ignition, not ranking.
- **Configuration.** `[syneidesis]` gains `precision_weighting` (default `true`), `precision_sample_weight`, `precision_warmup_samples`, `precision_bounds`, and `arousal_contrast_gain` (default 8.0; 0 disables the contrast). A `RuleBasedSalience` built without a precision tracker (the offline harnesses) is neutral, so the ablation arms are unchanged.
- **The repository rule on the precision term.** `thymos-active-inference-affect` says the precision term must not change before the workspace-mediation ablation has run, because the change alters what every experiment tests. No live experiment has run, so no result is invalidated; the operator chose the change on 2026-10-08, and the planned ablation will test this selector. That design note is amended to record the decision.

## Capabilities

### Modified Capabilities

- `syneidesis`: precision-weighted priority and arousal contrast in the v1 salience strategy.
- `thymos`: the modulator's contrast gain.

## Impact

- **Code:** new `kaine/workspace/precision.py`; `kaine/workspace/salience.py`; `kaine/modules/thymos/modulator.py`; `kaine/boot/wiring.py`; `kaine/cycle/__main__.py`; `config/kaine.toml`.
- **Behaviour:** which module wins now depends on how informative its surprise has been; above baseline arousal alerts are amplified and baseline events suppressed, so actionable broadcasts and speech become more likely under arousal. The confidence threshold and report bars are unchanged and stay provisional.
- **Docs:** `docs/08-cognitive-cycle/global-workspace.md`, `docs/09-modules/thymos.md`, `docs/appendix-a-configuration/core.md`.
- **Paper:** §3.2, §3.5 (Thymos), Appendix A.1, Table A1.
