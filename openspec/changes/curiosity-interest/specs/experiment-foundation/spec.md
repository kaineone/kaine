## ADDED Requirements

### Requirement: The run manifest records the curiosity scheme
The run context SHALL carry `curiosity_scheme` 2, curiosity as heterostatic interest; a manifest without it means 1, curiosity as a deficit.

#### Scenario: A new run's manifest
- **WHEN** a run context is minted and its manifest written
- **THEN** the manifest has `curiosity_scheme` 2
