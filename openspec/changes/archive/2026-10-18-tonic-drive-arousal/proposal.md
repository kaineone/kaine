## Why

The third test boot (main c4afcdd2, 2026-10-17) confirmed that habituation works: median arousal fell from 0.85 to 0.40. Access then turned into a sawtooth. For a few minutes after each sleep reset the alert rates are zero, the habituation factor is 1 and access is high; after that, only audition alerts reach the access threshold (paper A.11, reachability at resting arousal), and 17 of 41 minutes had 0 to 3 accessed broadcasts. Speak and think intents fell from 85 and 92 to 20 and 28. Every input to arousal is phasic, so a habituated entity in a steady scene sits at the baseline `a_0` even while its drives are deprived (curiosity, boredom and restlessness sat near 0.9 for most of the run).

Two cited accounts say a deprived entity should not rest there:
- Aston-Jones and Cohen (2005, Annu Rev Neurosci 28:403-450, abstract): "When utility in the task wanes, LC neurons exhibit a tonic activity mode, associated with disengagement from the current task and a search for alternative behaviors (exploration)."
- Hull: drive multiplies the reaction potential of learned responses (Hull 1943; restated in Hull 1949, Psychol Rev 56:67-76, Postulate IX, sEr = D x V x K x J x sHr). Postulate V.D adds that "at least some drive conditions tend partially to motivate into action habits which have been set up on the basis of different drive conditions", the general-energizer reading.

KAINE's drives are deficits whose reduction is the reward (paper section 3.5, Hull 1943; Keramati and Gutkin 2014), so a deprived dominant drive is the sustained absence of reward, the waning utility of the current engagement. That supports the dominant drive value `v*` (already defined in A.4) over boredom alone, which would ignore an unmet curiosity or restlessness. It also supports `v*` over the drive mean, which drives without an input channel dilute (the social drive stays at 0 until a voice is heard). Hull's own postulate is partial cross-drive energizing, not a sum, so the largest drive is the conservative aggregate.

## What Changes

- Paper A.4 item 3 (PR #47, commit 5ca8583): arousal relaxes toward `a_inf = a_0 + gamma_D (1 - a_0) v*` instead of `a_0`, with `v*` the dominant drive's value at the start of the update and `gamma_D = 0.2` (Table A1, design). Dominance still relaxes toward its baseline. Phasic steps are unchanged, the sleep reset still returns arousal to `a_0` and drives to 0, so `a_inf = a_0` right after sleep. The workspace contrast gain and the regulation intensity keep `a_0` as their reference.
- New `[affect].drive_arousal_gain` (default 0.2, in `[0, 1]`); 0 restores the previous build exactly.

### Choosing gamma_D

Replay of both test boots through the current affect module, with the recorded alerts, intents and broadcasts held fixed, sampled on a 1 s grid. The reachability arousals are those of paper A.11: about 0.37 for vision, sequence, interoception and affect alerts, 0.45 for an audition alert to reach the think bar, 0.63 to reach the speak bar. Rows are for the 1017b boot (32 min), with the 1017 boot (46 min) in brackets.

| gamma_D | Target at v* = 0.9 | Arousal median | At least 0.37 | At least 0.45 | At least 0.63 |
|---|---|---|---|---|---|
| 0 (main) | 0.300 | 0.410 [0.391] | 58% [55%] | 44% [39%] | 26% [23%] |
| 0.15 | 0.394 | 0.496 | 99% | 61% | 32% |
| **0.2** | 0.426 | 0.524 [0.510] | 99% [100%] | 80% [72%] | 35% [31%] |
| 0.3 | 0.489 | 0.581 [0.568] | 99% [100%] | 99% [99%] | 41% [38%] |
| 0.5 | 0.615 | 0.692 [0.686] | 99% [100%] | 99% [99%] | 83% [72%] |
| 0.7 | 0.741 | 0.804 [0.798] | 99% [100%] | 99% [100%] | 99% [99%] |

The replay with gamma_D 0 reproduces the live median (0.410 against 0.400). `v*` was at least 0.7 for 92% [91%] of the time (median 0.90): it climbs from 0 after each sleep reset to 0.73 within 30 s and 0.9 within 90 s, and stays there because boredom is relieved only by alert excess and curiosity only by learning progress. With the dominant drive between its threshold (0.7) and its deprived level (0.9), gamma_D 0.2 puts the resting target at 0.40 to 0.43: above the 0.37 that the non-audition alerts need and below the 0.45 think bar, so a deprived entity accesses its other alerts at rest and reaches a report bar only with a phasic step. Any gamma_D in [0.12, 0.23] meets those two bounds; 0.3 crosses the think bar tonically, and 0.5 and 0.7 approach or cross the speak bar, so the entity would report constantly. With satisfied drives (`v*` = 0) the target is exactly `a_0`. In these boots that state only lasts the first 20 s after each reset, when the phasic post-reset alerts dominate.

The replay cannot show the loops through access. More access brings more intents, which relieve restlessness and lower `v*` while it is the largest drive: negative feedback. Boredom falls only with alert excess, so in a monotonous scene `v*` and the target stay up until sleep. That is the exploration the adaptive-gain account describes, and it is named as a third loop in the paper's stability paragraph (section 6.4).

## Capabilities

### Modified Capabilities

- `affect`: arousal relaxes toward a drive-raised target.

## Impact

- `kaine/modules/affect/module.py`, `kaine/boot/factories/affect.py`, `config/kaine.toml`, `docs/09-modules/affect.md`, `docs/appendix-a-configuration/modules.md`, affect tests.
- Behaviour: a deprived entity rests at an arousal of about 0.40 to 0.43 rather than 0.3, which raises the contrast gain, the tonic access drive and the share of accessed broadcasts. Phasic responses ride on top of it.
