## ADDED Requirements

### Requirement: Drives are setpoint deficits with relief
Each Thymos drive SHALL evolve between events by the exact solution of linear build and decay toward the equilibrium `beta u / (beta u + delta)`, with build signal `u` in `[0, 1]`, and SHALL be reduced by a consummatory event of strength `c` in `[0, 1]` to `D (1 - rho c)`, with `rho` the drive's relief gain. Curiosity SHALL be relieved by perceptual learning progress, boredom by perceptual alerts, the social drive by a new operator interaction, and restlessness by Volition intents other than REST. With the shipped rates, the full-deprivation equilibrium `beta / (beta + delta)` of every drive SHALL exceed its threshold.

#### Scenario: Curiosity falls when perception is learning
- **WHEN** perceptual normalised errors fall steadily over many reports
- **THEN** curiosity decreases

#### Scenario: Drives stay bounded
- **WHEN** a drive's build signal is 1 for an hour of subjective time with no relief
- **THEN** its value stays at or below `beta / (beta + delta)`

### Requirement: Valence tracks the rate of change of prediction error
Thymos SHALL move valence toward `tanh(valence_progress_gain * g + (W - 0.5) + c)` with time constant `valence_time_constant_s`, where `g` is the signed perceptual learning progress, `W` Soma's last wellness, and `c` the perceived pleasantness from operator coupling.

#### Scenario: Errors falling is pleasant
- **WHEN** perceptual normalised errors fall steadily on a healthy host
- **THEN** valence becomes positive

### Requirement: Appraisal novelty reflects surprise
Thymos SHALL compute the novelty appraisal check as `1 - prod (1 - s_m)` over coalition members that carry a normalised error ratio `r`, with `s = clip(ln r / ln 3, 0, 1)`.

#### Scenario: Surprise is reachable
- **WHEN** the coalition holds a perceptual report with normalised error ratio 3 and pleasantness and goal significance are near zero
- **THEN** the categorical emotion is SURPRISE

## REMOVED Requirements

### Requirement: Appraisal nudges are per unit time
**Reason**: Valence and arousal no longer take per-broadcast appraisal nudges; valence relaxes toward a target in continuous time and surprise reaches arousal through the perceptual-alert path.
**Migration**: Delete `appraisal_reference_interval_s` from `[thymos]` in `config/kaine.toml`; the key is now rejected as unknown.
