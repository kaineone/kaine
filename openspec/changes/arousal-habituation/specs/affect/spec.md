## ADDED Requirements

### Requirement: Perceptual arousal habituates to the base alert rate
On each `vision.report` or `audition.perception` event whose `alert` is true, the affect module SHALL raise arousal by `gamma_a * h * min(nu_cap, max(0, max(r_err, r_chg) - 1))`, where `h = max(clip_[0,1](r_f / max(r_s, r_0) - 1), exp(-r_s * tau_s))` is computed from the perceptual alert rates before this alert adds `1/tau_f` and `1/tau_s` to them (paper A.4 item 1). The presentation term `exp(-r_s * tau_s)` SHALL use the unfloored `r_s`. The boredom alert excess SHALL be unchanged.

#### Scenario: Alerts at a steady base rate leave arousal at baseline
- **WHEN** change alerts arrive every 5 s for 600 s with the module ticking every second
- **THEN** after the first 300 s every alert's habituation factor is 0, and from 450 s arousal stays within 0.01 of baseline

#### Scenario: A burst above the habituated rate raises arousal
- **WHEN** after that habituated stream five change alerts with change ratio 4.0 arrive 0.5 s apart
- **THEN** arousal rises above baseline by at least 0.3

#### Scenario: A first presentation gets the full step
- **WHEN** a fresh module receives one alert with change ratio 3.0
- **THEN** arousal rises by 0.15 x 2.0

#### Scenario: An isolated alert after a long quiet arouses again
- **WHEN** after the habituated stream 600 s pass with no alert and one alert with change ratio 3.0 arrives
- **THEN** its habituation factor is above 0.9 and arousal rises by more than 0.25

#### Scenario: The first alert after a sleep reset gets the full step
- **WHEN** the habituated module is reset by sleep and then receives one alert with change ratio 3.0
- **THEN** arousal rises by 0.15 x 2.0

### Requirement: The novelty check reads the error and change ratios with familiarity
`_score_snapshot` SHALL compute novelty as `1 - prod_e(1 - s_e)` over the selected events whose payload carries a positive finite `normalised_error` or `normalised_change`, with `s_e = clip_[0,1](ln(rho_e) / ln 3)` and `rho_e` the larger of the two ratios, and 0 when no event carries one. For `vision.report` and `audition.perception` events, `s_e` SHALL be multiplied by the habituation factor `h` at the appraisal. The perceived-emotion contribution SHALL be added as before.

#### Scenario: A change alert during a burst is novel
- **WHEN** the alert rates show a burst (`h` = 1) and the coalition holds a vision report with `normalised_error` 0.99 and `normalised_change` 3.0
- **THEN** novelty is 1.0

#### Scenario: A habituated stream is familiar
- **WHEN** `h` is 0 and the coalition holds the same vision report
- **THEN** novelty is 0.0

#### Scenario: Other processors are not discounted
- **WHEN** `h` is 0 and the coalition holds a sequence report with `normalised_error` 3.0
- **THEN** novelty is 1.0
