## MODIFIED Requirements

### Requirement: Shared verdict schema
The system SHALL provide a shared `Verdict` schema (outcome in WIN / NULL /
NEGATIVE / NOT_EXERCISED for comparative experiments and PASS / FAIL for safety
gates, plus an optional detail string and metrics map) with a stable serialization,
and the active-inference benchmark and enforcement red-team reports SHALL include a
`verdict` field using it without removing their existing fields. NOT_EXERCISED SHALL
mean that the comparison did not take place; it SHALL NOT be reported as a NULL and
SHALL NOT be counted as evidence for or against an effect.

#### Scenario: Experiments emit the shared verdict
- **WHEN** the AIF benchmark and the red-team each emit their report
- **THEN** each report contains a `verdict` object whose `outcome` is one of the shared schema's values

#### Scenario: NOT_EXERCISED serialises as its own value
- **WHEN** a verdict with outcome NOT_EXERCISED is serialised
- **THEN** its `outcome` is the string `"NOT_EXERCISED"`, distinct from `"NULL"`

## ADDED Requirements

### Requirement: Unexercised experiments stay out of the family-wise correction
The suite SHALL leave an experiment whose verdict is NOT_EXERCISED out of the
Holm-Bonferroni family, because it ran no test and has no p-value. The family-wise
view SHALL list such experiments by name under `not_exercised`, and the printed
report SHALL name them as not exercised and outside the family.

#### Scenario: An unexercised harness is not a member of the family
- **WHEN** the workspace-mediation harness is NOT_EXERCISED in a suite run
- **THEN** `workspace_mediation` is absent from the family-wise comparisons, the family size counts only the remaining p-values, and `workspace_mediation` appears under `not_exercised`

#### Scenario: An exercised harness stays in the family
- **WHEN** the workspace-mediation harness gives WIN, NULL or NEGATIVE
- **THEN** its WIN sign-test p-value is a member of the family and `not_exercised` is empty
