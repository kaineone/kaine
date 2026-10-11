## ADDED Requirements

### Requirement: The research log carries the paired evaluations
The curated research log SHALL copy `null_prediction_error` and `mean_prediction_error` from `topos.report`, `soma.report` and `audition.perception`, and the post-run range sweep SHALL require both to be non-negative.

#### Scenario: A processor report is logged with its paired evaluations
- **WHEN** Soma publishes a report with `context_gain` -0.05, `null_prediction_error` 0.5 and `mean_prediction_error` 0.8
- **THEN** the research record carries all three values
