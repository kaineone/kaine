## ADDED Requirements

### Requirement: A wizard re-run can turn an opt-in off
Answering No on a re-run SHALL turn off research-metrics submission and remove the CL1 plugin configuration the wizard owns. Answering No to state encryption while it is on SHALL keep it on and say why, because disabling it would make encrypted state unreadable.

#### Scenario: Declining research submission on a re-run
- **WHEN** the operator file has `research_submission.enabled = true` and the operator answers No
- **THEN** the saved file has `research_submission.enabled = false`

#### Scenario: Declining encryption while it is on
- **WHEN** state encryption is enabled and the operator answers No
- **THEN** encryption stays enabled, and the wizard explains that turning it off needs a decrypting migration
