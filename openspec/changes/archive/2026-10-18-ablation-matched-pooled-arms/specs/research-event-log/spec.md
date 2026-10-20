## ADDED Requirements

### Requirement: The workspace record names the arm
The research log's workspace record SHALL copy `arm` from the broadcast metadata when present, so the records of each run say which arm of the planned ablation produced them.

#### Scenario: A matched broadcast is recorded with its arm
- **WHEN** a broadcast with metadata `arm` "matched" is recorded
- **THEN** the workspace record has `arm` "matched"
