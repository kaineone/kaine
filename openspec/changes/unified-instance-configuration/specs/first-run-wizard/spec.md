# Spec Delta

## ADDED Requirements

### Requirement: Wizard covers all basic-tier configuration
The wizard SHALL present every `basic`-tier key from the configuration reference
during first-run setup. Keys the operator skips keep their shipped defaults. The
wizard SHALL NOT present `standard` or `advanced` keys unless the operator requests
them.

#### Scenario: Wizard omits a basic-tier key
- **WHEN** the reference adds a new `basic`-tier key
- **THEN** a test fails if the wizard's question set does not include it
