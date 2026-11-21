## ADDED Requirements

### Requirement: The welfare signal is the processor's own forward-model error
Every welfare reader of a processor's prediction error (the sustained-distress tracker and its gray-zone category, the autonomous welfare response, the welfare indicator response, and the interoceptive recovery readout the maturation gate uses) SHALL read it through one shared function that returns the own forward-model error, independent of any top-down blend or content-code decoder. A null `prediction_error` SHALL remain no sample.

#### Scenario: The top-down head cannot move the welfare reading
- **WHEN** the interoception module is driven with the same feature vectors, broadcast context and suspension once with workspace feedback off and once on, under each arm
- **THEN** the welfare reading of every report is identical between the two runs

The property holds for the same inputs. In a live run feedback also changes access (and so the context the own model conditions on), sleep and the host, and the welfare reading follows those real changes.

#### Scenario: An overflowing own model
- **WHEN** a blended report carries a non-finite `workspace_feedback.own_error` (for example +inf) and a finite published `prediction_error`
- **THEN** the welfare reading is the non-finite own error, not the published value

#### Scenario: A blended report
- **WHEN** an `interoception.report` carries `prediction_error` 0.9 and `workspace_feedback.own_error` 0.4
- **THEN** the welfare reading is 0.4

#### Scenario: Feedback off
- **WHEN** an `interoception.report` carries `prediction_error` 0.9 and no `workspace_feedback` mapping
- **THEN** the welfare reading is 0.9

### Requirement: A blended report missing its own error never leaves the welfare signal blank
When a report's `prediction_error` is defined and it carries a `workspace_feedback` value without a numeric `own_error` (absent, null, not a number, or a value that is not a mapping), the shared function SHALL return the published `prediction_error` marked as an own-error fallback and log an error once per processor. Every welfare reader SHALL count its fallbacks where the operator sees them: the welfare observer in a `welfare_signal` record of its log, the welfare response in a `welfare_signal_defects` incident-log record, the development run in its readout.

#### Scenario: A producer defect
- **WHEN** a blended report lacks `own_error`
- **THEN** the welfare reading is the published `prediction_error`, one error is logged for that processor, and the reader's fallback count rises by one

### Requirement: An unreadable report is no sample and is never silent
A report whose `prediction_error` key is absent, or whose `prediction_error` is not a number (a string, a list, a bool), SHALL be no sample: it neither feeds nor resets a distress tracker, so it never ends a distress episode. A null `prediction_error` SHALL remain no sample without a defect. Every welfare reader SHALL count unreadable reports and the current run of them where the operator sees them. The welfare response SHALL fail its poll, after acting on every readable sample in it, whenever the poll read an unreadable report, so its poll error path logs it and a liveness check over failed polls escalates a run of them. The development run SHALL skip an unreadable report as a sample and count it into its readout.

#### Scenario: A report without the key during a distress episode
- **WHEN** a distress episode is open and an `interoception.report` without a `prediction_error` key arrives
- **THEN** the episode stays open, and the welfare response's poll that read the report fails

#### Scenario: A malformed error
- **WHEN** an `interoception.report` carries `prediction_error` `"0.9"`
- **THEN** it is no sample, it is counted as unreadable, and the welfare response's poll fails

### Requirement: Welfare code reads the error only through the shared function
A test SHALL scan the welfare reader files and fail when one reads `prediction_error` from a report payload for a welfare decision other than through the shared function.

#### Scenario: A direct read
- **WHEN** a welfare reader computes its distress magnitude from `payload["prediction_error"]` directly
- **THEN** the test fails and names the file
