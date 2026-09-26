## ADDED Requirements

### Requirement: Goals survive preservation
Thymos SHALL include its goal ledger in its serialized state — each goal's id, description, priority, state, and created and completed times — and SHALL restore it on deserialize, so a revived entity holds the goals it held when preserved. A restore SHALL NOT publish goal lifecycle events. Invalid goal entries SHALL be dropped with a log, and the rest SHALL load.

#### Scenario: Goals round-trip
- **WHEN** Thymos holds an active, a completed and an abandoned goal and is serialized and restored into a fresh Thymos
- **THEN** the restored ledger holds the same three goals with the same ids, states and priorities, and relevance scoring counts only the active one

#### Scenario: A snapshot without goals
- **WHEN** Thymos is restored from a snapshot that has no goals key
- **THEN** its goal ledger is left as it was
