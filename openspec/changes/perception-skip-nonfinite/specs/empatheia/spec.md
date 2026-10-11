## ADDED Requirements

### Requirement: An observation without a defined error leaves the error average alone
When an `audition.emotion` event carries a null `prediction_error`, Empatheia SHALL fold the observation into the agent model without updating `mean_prediction_error`, and the placeholder fold of an `audition.transcription` event SHALL likewise leave it unchanged, so the average is never seeded or pulled toward a made-up 0. Every other part of the fold SHALL be unchanged.

#### Scenario: A null error does not seed the average
- **WHEN** Empatheia folds an emotion event with a null `prediction_error` and then a transcription event for a new agent
- **THEN** the agent's interaction count is 2 and its behavioral summary has no `mean_prediction_error`, and a later emotion event with an error of 0.3 sets it to 0.3
