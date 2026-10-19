## ADDED Requirements

### Requirement: Tone records carry the stream-qualified id
The research log's `audition.emotion` record SHALL carry in `entry_id` the event's stream-qualified id `<stream>:<entry_id>`, the id the cycle gives the event as a workspace candidate and the `entry_id` of the event as a member of a `workspace.broadcast` record. This replaces the bare bus entry id that change `tone-analysis-inputs` put there.

#### Scenario: A tone event's id matches its member id
- **WHEN** the research log records an `audition.emotion` event read from `audition.out` with bus id `5-0`
- **THEN** the record's `entry_id` is `audition.out:5-0`
