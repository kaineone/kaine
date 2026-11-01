## ADDED Requirements

### Requirement: The conversation collection is a persisted kind of its own
With conversation memory enabled, the episodic memory module SHALL treat `conversation` as a persisted collection kind. It SHALL count the collection in the store size and the storage budget, draw the wake's replay candidates from it by `born_sleep`, and search it in snapshot-cued recall. The collection SHALL always be stored through the encrypted conversation store, never through the configured backend.

#### Scenario: Pruning sees the conversation collection
- **WHEN** a sleep prunes for the storage budget and the conversation collection holds weak traces
- **THEN** those traces are candidates for pruning by the same rule as other traces

### Requirement: No conversation collection exists when conversation memory is off
With conversation memory disabled, the episodic memory module SHALL create no `conversation` collection, and its collection list SHALL be unchanged.

#### Scenario: Disabled leaves the collection list unchanged
- **WHEN** conversation memory is disabled
- **THEN** `persisted_collection_names()` returns the names it returns without this change

### Requirement: Replay of a conversation trace keeps its text off the main bus
When a sleep replays a conversation trace, the `episodic_memory.replay` event on the main bus SHALL carry `memory_id`, the affect values and the timestamps, and no `text`. The trace text SHALL travel only on the volatile instance, keyed by the main-bus entry id.

#### Scenario: A replayed conversation leaves no gist in the append-only file
- **WHEN** a conversation trace is replayed
- **THEN** no main-bus stream entry holds its gist, account or `said`

### Requirement: Own speech in broadcast traces passes the overlap guard
While conversation memory is enabled, the episodic memory module SHALL pass the text of each `external_speech` and `internal_speech` member through the overlap guard before serializing the broadcast trace. A withheld text SHALL be stored as `<withheld: heard overlap>`.

#### Scenario: Repeated heard words are not stored as the entity's own
- **WHEN** the entity says aloud a sentence that repeats eight consecutive words it heard 20 s earlier
- **THEN** the broadcast trace holds the entity's speech with `(their words)` in place of the repeated run
