## ADDED Requirements

### Requirement: The store classifies and keeps the joined event
The episodic memory module SHALL declare `reads_spoken_text` and SHALL apply the shared heard rule to each member as joined with its companion entry, so classification is the same as when words rode the main bus. It SHALL keep the entity's own speech with its words from the companion entry and SHALL store it as `<words unavailable>` when the entry is missing. A heard member SHALL be stored as `<heard omitted>` whether or not its companion entry exists.

#### Scenario: Own speech is remembered
- **WHEN** an accessed `external_speech` member's companion entry exists
- **THEN** the trace keeps its words as spoken

#### Scenario: Heard speech is never kept
- **WHEN** an accessed operator transcription's companion entry exists
- **THEN** the trace stores the member as `<heard omitted>`

#### Scenario: Own words lost on a restart
- **WHEN** an accessed `internal_speech` member's companion entry is missing
- **THEN** the trace stores it as `<words unavailable>`
