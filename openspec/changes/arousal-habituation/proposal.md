## Why

A live test boot of main e266aa88 (2026-10-17, 46 minutes) found two affect defects.

1. Arousal saturates. Every vision or audition alert raises arousal by `gamma_a * min(nu_cap, max(0, max(r_err, r_chg) - 1))`, and the vision change alert needs a change ratio of at least 2, so every alert adds at least 0.15. The stimulus produced a pair of change alerts about every 15 s (median excess 2.8), while arousal relaxes at 0.05 per second. Arousal ran at a median of 0.85 and a maximum of 0.999, and 99% of the affect states were above 0.5. The paper (section 3.5, A.4) says arousal tracks changes in surprise more than its sustained level, and that even a still scene alerts at a steady base rate because the A.2 criterion self-calibrates; base-rate alerts must therefore not hold arousal high. Phasic locus coeruleus responses to a repeated stimulus habituate within a few presentations (Herve-Minvielle and Sara 1995, NeuroReport 6(10):1363-1368; Vankov, Herve-Minvielle and Sara 1995, Eur J Neurosci 7(6):1180-1187).
2. Novelty ignores change. The appraisal's novelty check reads only `normalised_error` (live median 0.99), so the categorical emotion stayed neutral through change-driven activity. Scherer's novelty check covers suddenness, familiarity and predictability (Sander, Grandjean and Scherer 2005), and arousal already reads the larger of the error and change ratios.

A replay of the boot's recorded event stream through the affect module (scratchpad replay of the main run, 418 perceptual alerts, 22,795 broadcasts) reproduced the live arousal (replay median 0.873 against the live 0.858). With the habituation factor below, arousal outside the first 150 s after a boot or sleep reset has a median of 0.345 (baseline 0.3) and is above 0.5 in 10% of broadcasts; a synthetic burst of five change alerts in 2 s still lifts arousal from 0.46 to 0.996. Reading the factor after the alert's own increment instead never habituates (median 0.72), and subtracting the boredom margin `m_B` after the increment gives a median of 0.40 with 23% above 0.5. Reading the change ratio in the novelty check raises the broadcasts with novelty of at least 0.6 from 2 to 785; the habituation factor brings them to 261, so a familiar periodic cut is no longer novel.

## What Changes

- Paper A.4 item 1 (PR #47, commit 33cb4c4): each perceptual alert's arousal step is multiplied by the habituation factor `h = clip_[0,1](r_f / max(r_s, r_0) - 1)`, read from the alert rates before this alert adds to them. `h` uses the existing `r_f`, `r_s`, `r_0` and no new parameter; it is the alert excess of A.4 without the margin `m_B`.
- Paper A.4 novelty: the novelty check is `1 - prod_e(1 - s_e)` over coalition members with an error or change ratio (0 if none), with `s_e = clip_[0,1](ln rho_e / ln 3)` for the larger ratio `rho_e`, times `h` at the appraisal for vision and audition reports.
- `Affect` gains `_habituation()` and uses it in the perceptual alert path and in `_score_snapshot`. The boredom alert excess is unchanged.

## Capabilities

### Modified Capabilities

- `affect`: perceptual arousal habituates to the base alert rate, and the appraisal's novelty reads the change ratio and the same habituation.

## Impact

- `kaine/modules/affect/module.py`, `docs/09-modules/affect.md`, affect tests.
- Behaviour: arousal rests near baseline under base-rate alerts and rises on bursts above the habituated rate; the first alert after a quiet spell or a reset adds no arousal (its rate excess is 0), the following ones in a burst do. Novelty can now come from a change, and a habituated perceptual stream is familiar. The replay cannot reproduce the arousal feedback on the fovea and the attended auditory window, so the live alert stream under lower arousal may differ.
