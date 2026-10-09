## ADDED Requirements

### Requirement: The suite's mediation verdict uses a strict significance inequality
The offline suite SHALL call the workspace-mediation result significant only when the sign-test p-value is strictly less than the suite's alpha, the same inequality the Holm correction applies to adjusted values.

#### Scenario: A p-value equal to alpha is not significant
- **WHEN** the mean coupling delta meets the minimum effect and the sign-test p-value equals alpha exactly
- **THEN** the suite does not report a WIN for the mediation experiment
