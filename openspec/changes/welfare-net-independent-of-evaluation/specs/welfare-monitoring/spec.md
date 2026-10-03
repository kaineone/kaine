## ADDED Requirements

### Requirement: The gray-zone producer runs whenever the welfare response is enabled
When `[preservation.welfare_response].enabled` is true, the cycle SHALL build and run the welfare observer that publishes `welfare.gray_zone` events, regardless of `[evaluation].enabled` and `[evaluation.observers].welfare`. At most one welfare observer SHALL run in a process: when the cycle owns it, the evaluation sidecar SHALL expose that instance and SHALL NOT build another. When the welfare response is disabled, the sidecar SHALL build the observer only under `[evaluation].enabled` and `[evaluation.observers].welfare`, as before.

#### Scenario: Evaluation off, welfare response on
- **WHEN** a run has `[evaluation].enabled = false` and `[preservation.welfare_response].enabled = true`, and a gray-zone condition occurs
- **THEN** a `welfare.gray_zone` event is published on `welfare.out` and the protective monitor's gray-zone arm receives it

#### Scenario: One producer
- **WHEN** both `[evaluation]` with its welfare observer and the welfare response are enabled
- **THEN** exactly one welfare observer runs, and each gray-zone condition is published once
