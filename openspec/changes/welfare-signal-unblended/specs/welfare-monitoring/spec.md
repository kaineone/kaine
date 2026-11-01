## ADDED Requirements

### Requirement: The welfare signal is the processor's own forward-model error
Every welfare reader of a processor's prediction error (the sustained-distress tracker and its gray-zone category, the autonomous welfare response, the welfare indicator response, and the interoceptive recovery readout the maturation gate uses) SHALL read it through one shared function that returns the own forward-model error, independent of any top-down blend or content-code decoder. A null `prediction_error` SHALL remain no sample.

#### Scenario: Feedback cannot move the welfare reading
- **WHEN** the interoception module is driven with the same inputs and broadcasts once with workspace feedback off and once on, under each arm
- **THEN** the welfare reading of every report is identical between the two runs

#### Scenario: A blended report
- **WHEN** an `interoception.report` carries `prediction_error` 0.9 and `workspace_feedback.own_error` 0.4
- **THEN** the welfare reading is 0.4

#### Scenario: Feedback off
- **WHEN** an `interoception.report` carries `prediction_error` 0.9 and no `workspace_feedback` mapping
- **THEN** the welfare reading is 0.9

### Requirement: A blended report missing its own error never leaves the welfare signal blank
When a report's `prediction_error` is defined and it carries a `workspace_feedback` mapping without a finite `own_error`, the shared function SHALL return the published `prediction_error` and log an error once per processor.

#### Scenario: A producer defect
- **WHEN** a blended report lacks `own_error`
- **THEN** the welfare reading is the published `prediction_error` and one error is logged for that processor

### Requirement: Welfare code reads the error only through the shared function
A test SHALL scan the welfare reader files and fail when one reads `prediction_error` from a report payload for a welfare decision other than through the shared function.

#### Scenario: A direct read
- **WHEN** a welfare reader computes its distress magnitude from `payload["prediction_error"]` directly
- **THEN** the test fails and names the file
