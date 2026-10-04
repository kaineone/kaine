## ADDED Requirements

### Requirement: Workspace entries decode as broadcast events on read
On the read path (`read`, `range` and the cursor-advancing batch read), an entry with a `snapshot` field and no `type` field SHALL decode as an event with source `syneidesis`, type `workspace.broadcast`, the decoded snapshot as payload, the entry's timestamp, and salience equal to the highest selected member's salience clamped to [0, 1] (0.0 when there are no members). Publishing and `subscribe_workspace` SHALL be unchanged. An entry whose snapshot cannot be decoded SHALL still be skipped.

#### Scenario: A published broadcast is readable
- **WHEN** `publish_workspace` writes a snapshot and a consumer reads `workspace.broadcast` with `read`
- **THEN** it receives one event of type `workspace.broadcast` whose payload equals the snapshot

#### Scenario: A corrupt snapshot is skipped
- **WHEN** a workspace entry's `snapshot` is not valid JSON
- **THEN** the read skips it without raising
