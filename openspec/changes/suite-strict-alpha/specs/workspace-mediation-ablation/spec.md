## ADDED Requirements

### Requirement: The suite's mediation verdict uses the paper's significance inequality
The offline suite SHALL call the workspace-mediation result significant when the sign-test p-value is at most the suite's alpha (p <= alpha), the rule of paper Appendix A.8, and the Holm correction SHALL reject when an adjusted value is at most alpha, the non-strict rule of Holm (1979). One inequality serves both decisions in the report.

#### Scenario: A p-value equal to alpha is significant
- **WHEN** the per-seed contrasts give a WIN sign-test p-value equal to alpha exactly
- **THEN** the suite reports a WIN for the mediation experiment

#### Scenario: A p-value above alpha is not significant
- **WHEN** the WIN sign-test p-value is above alpha and the NEGATIVE one is too
- **THEN** the suite does not report a WIN or a NEGATIVE for the mediation experiment
