# The learning-progress floor under max pooling

## How the floor was calibrated

`learning_progress_floor` (Table A1 `lp_0` = 0.05, status "calibrated") was set by the offline calibration of the learning-progress-horizons change (#550). That calibration ran 16 awake hours on 3 seeds. Its inputs were the live audition path with a fresh forward model, recorded as error series for four feeds (the voice, a phase-randomized voice, the voice-free feed and a frozen forward model), and a vision error proxy fitted to the eighth boot (a plateau times a slow Ornstein-Uhlenbeck fluctuation, sd 0.15 and time constant 300 s, with per-report lognormal noise of 0.3). It replayed them through the shipped windowed estimator (60 s bins, 5,400 s span) and the drive equations. The floor's criterion was the frozen control, a forward model with nothing to learn: floor 0.02 gave 0.31 own curiosity reliefs per hour, 0.10 gave none but ended development by hour 4, and 0.05 gave 0.04 per hour (0.7 over 16 hours) while curiosity stayed below 0.75 through the first five hours.

## Reproduction

The calibration's evaluator and recorded series were re-run against the code at the calibration commit (fe6e5d82), with only the pooling line made switchable. Under mean pooling at 0.05 the frozen control gives 0.7 own reliefs over 16 hours, as recorded. At 0.02 it gives 5.3 (0.33 per hour) and at 0.10 none, also as recorded. The method reproduces.

## Re-run under max pooling

Own reliefs over 16 hours, mean of 3 seeds (voice feed / frozen control), and the voice feed's median curiosity in hours 0 to 5:

| Pooling, floor | Voice | Frozen | Voice curiosity median, h0 to h5 |
| --- | --- | --- | --- |
| mean, 0.05 (shipped) | 5.7 | 0.7 | 0.17 0.09 0.35 0.49 0.66 0.73 |
| max, 0.05 | 6.7 | 6.7 | 0.08 0.03 0.23 0.26 0.34 0.57 |
| max, 0.10 | 6.0 | 4.7 | 0.08 0.03 0.28 0.32 0.43 0.76 |
| max, 0.125 | 4.0 | 2.0 | 0.09 0.03 0.30 0.35 0.49 0.84 |
| max, 0.15 | 2.0 | 0.7 | 0.09 0.03 0.34 0.40 0.58 0.90 |
| max, 0.175 | 1.7 | 0.3 | 0.10 0.03 0.38 0.46 0.72 0.90 |
| max, 0.20 | 2.0 | 0.0 | 0.10 0.03 0.44 0.54 0.82 0.90 |

The largest of two noisy values sits above their mean, so at the shipped floor the frozen control gives ten times its calibrated relief rate. The criterion the calibration used, the frozen control at 0.7 own reliefs over 16 hours, is met at 0.15. Development then lasts into hour 5, about as long as with the mean at 0.05.

With the vision proxy refitted to the tenth boot's vision errors after hour 1 (10-minute medians vary by 21 percent, per-report residual sd 0.19; proxy sd 0.2, noise 0.19), the frozen control at 0.7 needs a floor of 0.20 under max pooling, and the mean itself would need 0.075 (it gives 4.0 at 0.05).

## Against the tenth boot's logged values

Replaying the tenth boot's logged per-processor learning progress through the boredom drive equation (steady state, no intents or alert excess), the hourly median of the steady state and the share of samples at or above the 0.7 threshold under max pooling:

| Hour | Floor 0.05 | Floor 0.15 |
| --- | --- | --- |
| h2 | 0.33, 0.00 | 0.50, 0.00 |
| h3 | 0.40, 0.00 | 0.65, 0.13 |
| h4 | 0.45, 0.00 | 0.78, 0.59 |
| h5 | 0.59, 0.10 | 0.90, 1.00 |
| h6 | 0.90, 1.00 | 0.90, 1.00 |
| h7 | 0.33, 0.10 | 0.50, 0.42 |

At 0.15 audition's own progress in h4 (0.06 to 0.24) is above the floor in 63 percent of samples instead of all of them, and most of the relief that max pooling gives is lost in h4 and h5.

## Status

The recalibrated floor (0.15) differs from Table A1 (0.05), and at that floor max pooling no longer keeps boredom under threshold in the hours the change was meant to help. This change keeps the Table A1 value; the floor is left for the paper to settle.
