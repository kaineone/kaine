## ADDED Requirements

### Requirement: The workspace trajectory records the graph without payloads
When `[evaluation].workspace_trajectory` is enabled, `TrajectoryRecorder` SHALL write one row per workspace broadcast holding the tick index, inhibition, salience scores, broadcast metadata and, for each selected member, its own entry id, source, type, salience, original timestamp and causal parent. A row SHALL NOT contain any member's payload or any module's state.

#### Scenario: A member with content and a vector
- **WHEN** a broadcast selects a member whose payload holds a text field and a numeric vector
- **THEN** the row holds the member's entry id, source, type, salience and timestamp and neither the text nor the vector

#### Scenario: No affect state
- **WHEN** a Thymos state is available while a row is written
- **THEN** the row does not contain it
