## ADDED Requirements

### Requirement: The restored posterior reaches the engine
When Nous is restored from a snapshot, the preserved posterior SHALL become both the module's last posterior and its inference engine's fallback posterior, so a degraded step after a revive (a planning timeout or crash) reports the preserved belief rather than the uniform prior. A posterior whose shape does not match the model's factors SHALL be ignored with a warning.

#### Scenario: A degraded first step after revive
- **WHEN** Nous is restored with a posterior and its first planning step times out
- **THEN** the step reports the restored posterior

#### Scenario: A mismatched posterior
- **WHEN** the snapshot's posterior has the wrong number of factors
- **THEN** the engine's fallback is left as it was and a warning is logged
