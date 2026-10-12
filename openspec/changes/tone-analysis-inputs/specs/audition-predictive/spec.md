## ADDED Requirements

### Requirement: The tone rule and the tone error ratio
Audition SHALL compute for each tone event the running error ratio nu~utt_t of the tone path: its error over the mean of the last W_P defined errors including the current one, and 0 when the error is not defined or the mean is 0 (paper A.2). With `[audition].tone_rule = "categorical"` (the default) a tone event whose classified tone is not neutral SHALL have the alert intensity and `alert` true, and a neutral one SHALL have Gamma_Aud(nu~utt_t) and `alert` false. With `tone_rule = "error_ratio"` (the tone variant of the on arm, paper A.8) every tone event SHALL have Gamma_Aud(nu~utt_t) and `alert` false. Each `audition.emotion` event SHALL carry `tone_error_ratio` (nu~utt_t), `tone_rule`, and `classified`, which is false when the classifier failed or reported a degraded result. A failed classification SHALL keep the alert intensity under the default rule and SHALL be graded by Gamma_Aud(nu~utt_t) with `alert` false under `error_ratio`. A tone event SHALL NOT carry `normalised_error`, which Affect reads as appraisal novelty. Any other `tone_rule` value SHALL be refused at construction.

#### Scenario: An emotional tone in the variant
- **WHEN** Audition with `tone_rule = "error_ratio"` classifies an angry tone whose error equals the running mean
- **THEN** the event's intensity is Gamma_Aud(1), halfway between the baseline and the alert level, and `alert` is false

#### Scenario: The default rule
- **WHEN** Audition with the default rule classifies a happy tone
- **THEN** the event has the alert intensity and `alert` true
