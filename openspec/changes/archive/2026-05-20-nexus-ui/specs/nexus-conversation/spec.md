## ADDED Requirements

### Requirement: Conversation route renders external speech only
The Nexus conversation route SHALL render only events sourced from
the `lingua.external` stream. Internal speech (`lingua.internal`),
beliefs, memories, and any other content from any other module SHALL
NOT appear. The page SHALL display the entity name resolved from
Eidolon's persisted self-model and the current Hypnos sleep-status
badge.

#### Scenario: External speech renders
- **WHEN** Lingua publishes an event on `lingua.external` with text
  "hello"
- **THEN** the conversation SSE stream emits that text within one
  bridge tick and the rendered page shows it under the entity name

#### Scenario: Internal speech blocked from conversation
- **WHEN** Lingua publishes an event on `lingua.internal`
- **THEN** the conversation SSE stream MUST NOT emit it

#### Scenario: Sleep badge follows Hypnos
- **WHEN** Hypnos publishes a `hypnos.began_rest` event followed by
  `hypnos.ended_rest`
- **THEN** the conversation page badge transitions sleeping →
  awake

### Requirement: Conversation history lookback bounded
The conversation view SHALL fetch at most
`conversation_history_lookback` past entries from `lingua.external`
on initial page load (default 50). Older messages SHALL be reachable
only via a `?since=<id>` query parameter.

#### Scenario: First load capped
- **WHEN** a client opens `/` and the stream contains 5000 entries
- **THEN** the rendered page contains at most 50 most-recent entries
