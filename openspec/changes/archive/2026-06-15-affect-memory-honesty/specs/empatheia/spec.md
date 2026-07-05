## ADDED Requirements

### Requirement: Empatheia skips agent-model fold on degraded emotion events

`Empatheia._handle_emotion()` SHALL skip the agent-model fold (and NOT
increment `interaction_count`) when the incoming `audition.emotion` payload
carries `"degraded": true`.  A non-running emotion model MUST NOT inflate
familiarity or interaction counts.

#### Scenario: degraded emotion event

- **WHEN** an `audition.emotion` event arrives with `"degraded": true`
- **THEN** Empatheia does not update the agent model
- **AND** interaction_count is not incremented

#### Scenario: real emotion event

- **WHEN** an `audition.emotion` event arrives without `"degraded": true`
- **THEN** Empatheia folds the observation into the agent model normally
