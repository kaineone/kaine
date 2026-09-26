## MODIFIED Requirements

### Requirement: Failures and optional engine methods pass through
A silicon result that timed out or errored SHALL be returned unchanged with no stimulation, and any attribute the wrapper does not define SHALL be forwarded to the inner engine.

#### Scenario: Revive seeding
- **WHEN** Nous calls `seed_posterior` on the wrapped engine after a revive
- **THEN** the call reaches the inner engine and returns its result

#### Scenario: Revive through KAINE's loader
- **WHEN** a Nous whose engine the CL1 plugin wraps restores a posterior that fits the model
- **THEN** KAINE's own engine holds that posterior, and KAINE logs neither that the engine cannot take the restored posterior nor that it does not match the model
