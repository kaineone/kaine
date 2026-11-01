## ADDED Requirements

### Requirement: A blended interoception report carries its own-model error
With workspace feedback on, every `interoception.report` whose `prediction_error` is defined SHALL carry a numeric `workspace_feedback.own_error` equal to the inner forward model's error for that reading (finite whenever the inner model's error is), including the first defined reading after a skip, readings before the top-down head has a scored error, and readings while suspended.

#### Scenario: The first defined reading after a skip
- **WHEN** feedback is on and the first reading with a defined error after a skipped one is published
- **THEN** the report's `workspace_feedback.own_error` is a number and equals the inner model's error
