# Spec Delta

## ADDED Requirements

### Requirement: content-weights-in-snapshot
The content encoder weights, decoder weights, and the current shared code `z_k` are included in the entity's preservation snapshot alongside the existing module states and feedback controller state.

#### Scenario: snapshot includes content state
- **WHEN** an entity with an active content level is preserved
- **THEN** `snapshot.metadata["workspace_content"]` contains the serialized encoder weights, decoder weights, and `z_k`

#### Scenario: revive restores content state
- **WHEN** an entity is revived from a snapshot containing `workspace_content` metadata
- **THEN** the content level restores its encoder weights, decoder weights, and `z_k` from the snapshot

#### Scenario: revive from a pre-content snapshot
- **WHEN** an entity is revived from a snapshot that does not contain `workspace_content` metadata
- **THEN** the content level initializes fresh (random encoder/decoder weights, zero `z_k`); no error is raised
