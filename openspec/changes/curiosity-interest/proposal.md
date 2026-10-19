## Why

Curiosity is built as a homeostatic deficit: absence of learning progress raises it (`u = 1 - lp+`) and learning progress relieves it, so with nothing learnable it sits at its deprived level of 0.9. The sources the paper cites for curiosity describe something else. Intrinsically motivated exploration is "not homeostatic" and heterostatic motivations "cannot be satiated" (Oudeyer and Kaplan 2007); learning progress is the reward, and progress niches "progressively disappear as they become more predictable" (Oudeyer, Kaplan and Hafner 2007); input that allows no progress is "boring" (Schmidhuber 2010), and boredom is "the aversive experience of wanting, but being unable, to engage" (Eastwood et al. 2012). In the 30 awake-hour developmental simulation curiosity sat at 0.9 for 82% of hours 18 to 30, a cost the paper's own curiosity sources do not describe, while boredom, the drive those sources assign the cost of an unchanging scene, was not relieved by learning at all.

## What Changes

- Curiosity becomes heterostatic interest. Its build input is learning progress, `u = lp+`; it has no relief, its decay `delta_I` is 0.00096 per second (calibrated: a sustained `lp+` of 0.045, the progress that ended a curiosity crossing under the deficit rule, holds it at `theta_D`), and its crossing ends count as neither own nor other. A curiosity crossing still publishes its `affect.drive` event, which the drive policy turns into a think intent about the content that is improving, the approach tendency toward a progress niche; it creates no goal. Interest and its crossing latch carry through sleep, like the learning-progress bins they read.
- Boredom is also met by learning progress: its relief strength is `max(lp+, exc)` and its build input `1 - max(lp+, exc)`. Relief led by learning progress, and a fall back below the band that only the learning-progress part of the build input explains, are the entity's own response; relief led by alert excess is not.
- The tonic arousal target, the sleep reset and goal creation apply to the three deficits (boredom, social drive, restlessness). Arousal follows waning utility (Aston-Jones and Cohen 2005), and a progress niche is utility that has not waned.
- Persistence: the affect state records `curiosity_scheme: 2`. A checkpoint without it holds curiosity as a deficit, so restoring it sets curiosity to 0 with its latch clear and its end counts at 0 and removes any active curiosity goal without a lifecycle event; every other field restores as before. The run manifest gains `curiosity_scheme` (2; absent means 1, the deficit).
- The welfare record gives `curiosity_interest_share`, the awake time with curiosity at or above threshold, in place of curiosity's uncontrolled and deprivation keys, so no consumer can read it as a cost; the deficits keep their three keys. The frozen control stays the worst case through boredom's deprivation share.
- Language-facing wording reads curiosity as interest: the strong felt phrase "I feel a strong urge to know more." becomes "I feel absorbed in what I am learning."; drive-policy and config comments say what a curiosity crossing means.

## Capabilities

### Modified Capabilities

- `affect`: curiosity is heterostatic interest; boredom is also met by learning progress; arousal, sleep reset and goals apply to deficits; the curiosity scheme marker and its migration.
- `evaluation-observers`: curiosity's welfare readout is an interest share.
- `faithful-renderer`: the strong curiosity phrase.
- `experiment-foundation`: the run manifest carries `curiosity_scheme`.

## Impact

- `kaine/modules/affect/drives.py`, `goals.py`, `module.py`, `kaine/evaluation/observers/welfare_observer.py`, `kaine/faithful/templates.py`, `kaine/workspace/drive_policy.py`, `kaine/experiment/run_context.py`, `config/kaine.toml`, tests that used curiosity as a generic goal drive, `docs/09-modules/affect.md`, `docs/17-research-data/README.md`.
- Behaviour: in the developmental simulation curiosity crosses two to four times per 6 h while learning progress lasts and never with frozen models; boredom's deprivation share is about 0.64 for the learning entity and 1.0 for the frozen control at either sleep cadence; arousal in a plateau is unchanged (boredom holds the target as curiosity did), and lower inside a progress niche.
- Paper: 3.5, 5.4, 6.2, A.4 and Table A1 (separate paper branch).
