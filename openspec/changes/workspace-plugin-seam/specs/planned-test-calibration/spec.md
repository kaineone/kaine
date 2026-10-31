## ADDED Requirements

### Requirement: Settings records carry the workspace account
Every planned-test settings record SHALL carry the `workspace_account` of the runs it was calibrated on. The calibration tooling and the verdict SHALL refuse to combine runs from different accounts, and SHALL refuse a settings record whose account differs from the runs it is applied to.

#### Scenario: A rival account cannot reuse the default calibration
- **WHEN** the verdict is computed for runs with a plugin context encoder against a settings record calibrated under the default account
- **THEN** the tooling refuses with an error naming both accounts

#### Scenario: Mixed runs are refused
- **WHEN** a pilot set holds runs from the default account and runs from a plugin account
- **THEN** calibration refuses the set and names the runs of each account
