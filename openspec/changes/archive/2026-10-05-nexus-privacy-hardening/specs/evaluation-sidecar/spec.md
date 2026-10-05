## ADDED Requirements

### Requirement: Workspace trajectory is filtered before persistence
`TrajectoryRecorder` SHALL pass the `selected` field of every workspace snapshot through the shared `PrivacyFilter` or an explicit allowlist before writing it to the JSONL sink. Internal speech, memory text, belief text, user input, and affect reasons SHALL NOT be persisted verbatim by default.

#### Scenario: Trajectory record excludes raw internal content
- **WHEN** a workspace broadcast contains internal speech or memory text in `selected`
- **THEN** the trajectory JSONL record contains only the filtered/allowlisted fields and no raw internal content

#### Scenario: Filtered trajectory still captures salience and metadata
- **WHEN** a workspace broadcast is processed
- **THEN** the record retains `tick_index`, `is_experiential`, `salience_scores`, and non-sensitive metadata

### Requirement: Workspace trajectory is opt-in
The shipped `config/kaine.toml` SHALL set `[evaluation].workspace_trajectory = false`. Operators who want a persistent workspace record MUST explicitly enable it.

#### Scenario: Shipped config does not record trajectory
- **WHEN** the committed `config/kaine.toml` is inspected
- **THEN** `[evaluation].workspace_trajectory` is false

#### Scenario: Enabling trajectory requires explicit operator action
- **WHEN** an operator runs with the shipped config
- **THEN** no `data/workspace_trajectory/` directory is created and no trajectory JSONL is written
