## Why

A live test boot of main e266aa88 (2026-10-17, 46 minutes) found two affect defects.

1. Arousal saturates. Every vision or audition alert raises arousal by `gamma_a * min(nu_cap, max(0, max(r_err, r_chg) - 1))`, and the vision change alert needs a change ratio of at least 2, so every alert adds at least 0.15. The stimulus produced a pair of change alerts about every 15 s (median excess 2.8), while arousal relaxes at 0.05 per second. Arousal ran at a median of 0.85 and a maximum of 0.999, and 99% of the affect states were above 0.5. The paper (section 3.5, A.4) says arousal tracks changes in surprise more than its sustained level, and that even a still scene alerts at a steady base rate because the A.2 criterion self-calibrates; base-rate alerts must therefore not hold arousal high. Phasic locus coeruleus responses to a repeated stimulus habituate within a few presentations (Herve-Minvielle and Sara 1995, NeuroReport 6(10):1363-1368; Vankov, Herve-Minvielle and Sara 1995, Eur J Neurosci 7(6):1180-1187).
2. Novelty ignores change. The appraisal's novelty check reads only `normalised_error` (live median 0.99), so the categorical emotion stayed neutral through change-driven activity. Scherer's novelty check covers suddenness, familiarity and predictability (Sander, Grandjean and Scherer 2005), and arousal already reads the larger of the error and change ratios.

A replay of the boot's recorded event stream through the affect module (418 perceptual alerts, 22,795 broadcasts, 4 sleep resets, plus a synthetic burst and a 120 s quiet window ending in one isolated alert) reproduced the live arousal (replay median 0.864 against the live 0.858). With the chosen factor, settled arousal (more than 150 s after a boot or reset) has a median of 0.352 and is above 0.5 in 13% of broadcasts, the burst lifts arousal from 0.48 to 0.996, and the first alert after each sleep reset keeps its full step. The burst term alone gives a first alert nothing, which contradicts the first-presentation response of Herve-Minvielle and Sara (1995). The presentation term `1/(1 + r_s tau_s)` decrements more slowly than the data (0.5 at the second presentation, where Vankov et al. report a response markedly diminished or absent) and leaves a residual at the base rate (settled median 0.416, 19% above 0.5), so the exponential form is used. Reading the change ratio in the novelty check raises the broadcasts with novelty of at least 0.6 from 2 to 785; the habituation factor brings them to 283.

## What Changes

- Paper A.4 item 1 (PR #47, commits 33cb4c4 and 710b4a0): each perceptual alert's arousal step is multiplied by the habituation factor `h = max(clip_[0,1](r_f / max(r_s, r_0) - 1), exp(-r_s tau_s))`, read from the alert rates before this alert adds to them. `r_s tau_s` is the expected count of recent alerts, so the presentation term, the chance of none, is 1 for a first alert after quiet or a sleep reset and decrements over repeats, as locus coeruleus responses do; the burst term (the alert excess of A.4 without the margin `m_B`) keeps alerts above the habituated rate arousing. No new parameter.
- Paper A.4 novelty: the novelty check is `1 - prod_e(1 - s_e)` over coalition members with an error or change ratio (0 if none), with `s_e = clip_[0,1](ln rho_e / ln 3)` for the larger ratio `rho_e`, times `h` at the appraisal for vision and audition reports.
- `Affect` gains `_habituation()` and uses it in the perceptual alert path and in `_score_snapshot`. The boredom alert excess is unchanged.

## Capabilities

### Modified Capabilities

- `affect`: perceptual arousal habituates to the base alert rate, and the appraisal's novelty reads the change ratio and the same habituation.

## Impact

- `kaine/modules/affect/module.py`, `docs/09-modules/affect.md`, affect tests.
- Behaviour: arousal rests near baseline under base-rate alerts and rises on bursts above the habituated rate; the first alert after a quiet spell or a sleep reset gets the full step and repeats decrement it; recovery follows `r_s`, so an isolated alert 120 s after a dense stream still gets little. Novelty can now come from a change, and a habituated perceptual stream is familiar. The replay cannot reproduce the arousal feedback on the fovea and the attended auditory window, so the live alert stream under lower arousal may differ.
