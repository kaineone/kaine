## ADDED Requirements

### Requirement: Drives are setpoint deficits with relief
Each Thymos drive SHALL evolve between events by the exact solution of linear build and decay toward the equilibrium `beta u / (beta u + delta)`, with build signal `u` in `[0, 1]`. Curiosity and boredom SHALL be relieved continuously, `D <- D exp(-rho c dt)`, so their relief does not depend on the perceptual report rate: curiosity with `c` the perceptual learning progress above a noise floor, boredom with `c` the excess of the fast perceptual alert rate over its slow, habituated rate beyond a margin. The social drive SHALL be relieved by a new operator interaction and restlessness by each Volition intent other than REST, each as `D <- D (1 - rho c)`. Here `rho` is the drive's relief gain. With the shipped rates, the full-deprivation equilibrium `beta / (beta + delta)` of every drive SHALL exceed its threshold.

#### Scenario: Curiosity falls when perception is learning
- **WHEN** the perceptual modules' raw prediction errors fall steadily over a minute of subjective time
- **THEN** curiosity decreases

#### Scenario: Drives build under stationary noise
- **WHEN** a perceptual stream with noisy but stationary errors and a steady base rate of alerts runs for ten minutes of subjective time
- **THEN** curiosity and boredom both cross their thresholds

#### Scenario: Relief does not depend on the report rate
- **WHEN** the same time course of falling errors arrives at 10 reports per second and, separately, at 5
- **THEN** curiosity ends within 0.05 in both runs

#### Scenario: Drives stay bounded
- **WHEN** a drive's build signal is 1 for an hour of subjective time with no relief
- **THEN** its value stays at or below `beta / (beta + delta)`

### Requirement: Valence tracks the rate of change of prediction error
Thymos SHALL move valence toward `clip(P + (W - 0.5), -1, 1)` with time constant `valence_time_constant_s`, where `P` is the appraisal's intrinsic-pleasantness check, `clip(tanh(valence_progress_gain * g) + c, -1, 1)`, `g` the signed perceptual learning progress from averages of raw prediction error over subjective time, `c` the appraisal contribution of a perceived speaker emotion, and `W` Soma's last wellness. A module's averages SHALL be seeded at its first positive error.

#### Scenario: Errors falling is pleasant
- **WHEN** the perceptual modules' raw prediction errors fall steadily on a healthy host
- **THEN** valence becomes positive

#### Scenario: A first-frame zero error does not depress valence
- **WHEN** a perceptual module reports a prediction error of 0 on its first frame and positive errors afterwards
- **THEN** the learning progress is computed from the first positive error, not from 0

### Requirement: Appraisal novelty reflects surprise
Thymos SHALL compute the novelty appraisal check as `1 - prod (1 - s_m)` over coalition members that carry a normalised error ratio `r`, with `s = clip(ln r / ln 3, 0, 1)`.

#### Scenario: Surprise is reachable
- **WHEN** the coalition holds a perceptual report with normalised error ratio 3 and pleasantness and goal significance are near zero
- **THEN** the categorical emotion is SURPRISE

## MODIFIED Requirements

### Requirement: Dimensional state with homeostatic drift
Thymos SHALL maintain a `DimensionalState` containing `valence`
(float in `[-1, 1]`), `arousal` (float in `[0, 1]`), and `dominance`
(float in `[-1, 1]`). On every internal tick arousal and dominance SHALL
drift toward their configured baselines by a configurable fraction
(`drift_rate_per_s`) of the elapsed subjective time, and valence SHALL
relax toward its target (see "Valence tracks the rate of change of
prediction error"), each clamped to the valid range for its dimension.
The configured baseline valence SHALL be the initial valence and the
valence after an affective reset.

#### Scenario: Drift moves valence toward baseline
- **WHEN** the state has `valence=0.8`, the baseline is 0.0, there is no
  learning progress, Soma's wellness is 0.5 and no perceived emotion is
  present (so the valence target equals the baseline), and 2.0 seconds pass
- **THEN** the new valence is between 0.0 and 0.8 (strictly less
  than the prior value)

#### Scenario: Drift moves arousal toward baseline
- **WHEN** the state has `arousal=0.8`, the baseline is 0.3, and
  `drift_rate_per_s=0.5` is applied for 2.0 seconds
- **THEN** the new arousal is between 0.3 and 0.8 (strictly less
  than the prior value)

#### Scenario: Clamping enforced on out-of-range inputs
- **WHEN** an update attempts to set `arousal=1.5`
- **THEN** the resulting state has `arousal == 1.0`

## REMOVED Requirements

### Requirement: Appraisal nudges are per unit time
**Reason**: Valence and arousal no longer take per-broadcast appraisal nudges; valence relaxes toward a target in continuous time and surprise reaches arousal through the perceptual-alert path.
**Migration**: Delete `appraisal_reference_interval_s` from `[thymos]` in `config/kaine.toml`; the key is now rejected as unknown.
