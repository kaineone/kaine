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

### Requirement: Unexercised experiments stay in the family-wise correction at p = 1
The suite's Holm-Bonferroni family SHALL be the set of p-value-producing
experiments fixed before the run. An experiment whose verdict is NOT_EXERCISED ran
no test; it SHALL stay in the family with a p-value of 1, so the family does not
shrink once the outcomes are known. Its own verdict SHALL stay NOT_EXERCISED and
SHALL NOT be reported as NULL. The family-wise view SHALL list such experiments by
name under `not_exercised` and mark their comparisons, and the printed report SHALL
name them as not exercised.

#### Scenario: An unexercised harness stays in the family at p = 1
- **WHEN** the workspace-mediation harness is NOT_EXERCISED in a suite run
- **THEN** `workspace_mediation` is a family-wise comparison with raw p-value 1, the family size is unchanged, the harness appears under `not_exercised`, and its experiment verdict is NOT_EXERCISED

#### Scenario: An exercised harness enters with its own p-value
- **WHEN** the workspace-mediation harness gives WIN, NULL or NEGATIVE
- **THEN** its WIN sign-test p-value is its family member and `not_exercised` is empty
