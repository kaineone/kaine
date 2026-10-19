## ADDED Requirements

### Requirement: Perceptual alerts raise arousal by the larger excess of the error and change ratios
On each `vision.report` or `audition.perception` event whose `alert` is true, the affect module SHALL raise arousal by `gamma_a * min(nu_cap, max(0, max(r_err, r_chg) - 1))`, with `gamma_a = 0.15`, `nu_cap = 4.0`, `r_err` the payload's `normalised_error` and `r_chg` its `normalised_change` (paper A.5 item 1). A ratio that is missing, not a number, or not finite SHALL be read as 0.0. An event whose `alert` is not true SHALL NOT raise arousal through this rule.

#### Scenario: A change alert raises arousal
- **WHEN** an alert report carries `normalised_error` 0.99 and `normalised_change` 3.0
- **THEN** arousal rises by 0.15 x 2.0

#### Scenario: An error alert is unchanged
- **WHEN** an alert report carries `normalised_error` 3.0 and `normalised_change` 0.5
- **THEN** arousal rises by 0.15 x 2.0, as before this change

#### Scenario: Both ratios present takes the larger
- **WHEN** an alert report carries `normalised_error` 2.0 and `normalised_change` 3.5
- **THEN** arousal rises by 0.15 x 2.5

#### Scenario: A report without the change ratio behaves as before
- **WHEN** an alert report carries `normalised_error` 2.5 and no `normalised_change`
- **THEN** arousal rises by 0.15 x 1.5

#### Scenario: A non-finite change ratio is ignored
- **WHEN** an alert report carries `normalised_error` 0.99 and a non-finite `normalised_change`
- **THEN** arousal does not change

#### Scenario: Non-alert reports never arouse
- **WHEN** a report with `alert` false carries `normalised_change` 5.0 and `normalised_error` 5.0
- **THEN** arousal does not change
