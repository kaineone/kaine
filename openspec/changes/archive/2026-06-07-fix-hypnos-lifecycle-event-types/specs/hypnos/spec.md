## ADDED Requirements

### Requirement: Lifecycle-event consumers use the canonical published types

Consumers of Hypnos's sleep lifecycle events SHALL filter on the canonical
published types — `hypnos.sleep.started` and `hypnos.sleep.completed` — and not
on any other variant. In particular the sleep-snapshot observer, the
voice-tracking observer, and the conversation sleep-state surface SHALL react to
`hypnos.sleep.started` / `hypnos.sleep.completed`, so they receive the events
Hypnos actually emits.

#### Scenario: Sleep snapshot observer records on the canonical events

- **WHEN** a `hypnos.sleep.started` then a `hypnos.sleep.completed` event are
  published on `hypnos.out`
- **THEN** the sleep-snapshot observer captures the before/after pair

#### Scenario: Voice-tracking observer logs on sleep completion

- **WHEN** a `hypnos.sleep.completed` event is published
- **THEN** the voice-tracking observer processes it

#### Scenario: Conversation sleep badge follows the canonical events

- **WHEN** `hypnos.sleep.started` then `hypnos.sleep.completed` are observed
- **THEN** the conversation sleep state becomes sleeping, then awake
