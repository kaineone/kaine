## ADDED Requirements

### Requirement: The tier documentation states current capability
The deployment-tier documentation SHALL describe what each tier runs today — including whether torch is required and which modules the tier profile disables — and SHALL label hardware that the program targets but does not yet support as a target, naming the phase that reaches it.

#### Scenario: Reader checks Tier 0
- **WHEN** an operator reads the Tier 0 column
- **THEN** it states that torch is required today and lists the modules the profile disables, and it does not claim that a retired phone runs every module
