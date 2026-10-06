## ADDED Requirements

### Requirement: A non-blocking read never starts from "$"
The bus SHALL refuse a non-blocking stream read whose cursor is `"$"`, raising an error that names the stream, because such a read can never return an entry. A consumer that follows a stream from "now" SHALL resolve its starting cursor once with `last_entry_id` before its first read. A blocking read from `"$"` SHALL remain allowed.

#### Scenario: The silent stall becomes an error
- **WHEN** `read_entries`, `read` or `read_entries_block` is called with the cursor `"$"` and no block time
- **THEN** it raises an error naming the stream

#### Scenario: Sleep reaches a module that follows hypnos.out
- **WHEN** Chronos, Topos or Audition has initialized and Hypnos then publishes `hypnos.sleep.started`
- **THEN** that module suspends its forward-model adaptation
- **AND** it resumes after `hypnos.sleep.completed`
