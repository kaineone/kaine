## ADDED Requirements

### Requirement: Only a pass that learned counts as consolidation
A training pass SHALL report whether it updated learned parameters. Phantasia SHALL count a pass toward `successful_training_passes`, and save weights after it, only when it did. A world model that does not learn (the fake world model) SHALL never produce consolidation evidence.

#### Scenario: The fake world model trains
- **WHEN** Phantasia runs a sleep training pass on the fake world model
- **THEN** `successful_training_passes` does not increase
