## ADDED Requirements

### Requirement: Greedy decoding only in study configurations
The language organ SHALL sample with the shipped `[language].temperature` (0.7) in general use, including the `first_configuration` profile. Greedy decoding (temperature 0) SHALL be set only by study configurations: the module-addition study's overlay and the workspace-mediation study configurations.

#### Scenario: An ordinary boot samples
- **WHEN** the configuration is loaded with the `first_configuration` profile and no study
- **THEN** `[language].temperature` is 0.7

### Requirement: An empty broadcast never replaces the organ's cached coalition
The language module SHALL cache the latest broadcast that is not inhibited and has at least one member. An empty pooled broadcast, which is not inhibited, SHALL leave the cache unchanged.

#### Scenario: An empty pooled broadcast after a coalition
- **WHEN** the language module has cached a coalition and then receives an empty pooled broadcast
- **THEN** the cached coalition is unchanged
