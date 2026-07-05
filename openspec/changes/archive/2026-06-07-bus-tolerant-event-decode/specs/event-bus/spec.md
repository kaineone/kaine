## ADDED Requirements

### Requirement: Resilient decode of stored entries on read

Reading stored entries SHALL be resilient to malformed or legacy entries. When
decoding an entry read from a stream, an empty or unparseable `salience` value
SHALL be treated as `0.0` (the floor of the valid range) rather than raising.
The `read` and `range` operations SHALL guard decoding per entry: if an entry
cannot be decoded at all, it SHALL be skipped (logged at debug level, since a
large legacy backlog would otherwise flood the log on every read), and the scan
SHALL continue. A single malformed stored entry SHALL NOT cause `read` or
`range` to raise.

A cursor-advancing consumer SHALL be able to advance past an entire batch of
undecodable entries. The bus SHALL expose a way to read a batch that reports the
id of the last entry *scanned* (decodable or not), so that when a whole batch
decodes to nothing the consumer still advances its cursor past it rather than
re-reading the same poison batch indefinitely.

This tolerance applies only to the read path. Publish-time validation is
unchanged: publishing an event with a missing or out-of-range salience SHALL
still be rejected.

#### Scenario: Empty salience on a stored entry decodes to the floor

- **WHEN** a stream contains an entry whose `salience` field is an empty string
- **AND** that entry is read via `read` or `range`
- **THEN** the entry decodes to an event with `salience == 0.0`
- **AND** no exception is raised

#### Scenario: A poison entry mid-stream does not wedge the reader

- **WHEN** a stream contains a malformed legacy entry followed by well-formed
  entries
- **AND** a consumer reads the stream from before the malformed entry
- **THEN** `read` returns without raising
- **AND** the consumer's cursor advances past the malformed entry on the next
  read rather than re-reading it indefinitely

#### Scenario: An undecodable entry is skipped, not fatal

- **WHEN** a stream contains an entry that cannot be decoded into an event
- **AND** that stream is read via `read` or `range`
- **THEN** the undecodable entry is omitted from the returned results
- **AND** the remaining well-formed entries in the batch are still returned

#### Scenario: A fully undecodable batch still advances the cursor

- **WHEN** an entire batch read from a stream consists of undecodable entries
- **THEN** the batch read reports no decoded events
- **AND** it reports the id of the last entry scanned, non-null
- **AND** a cursor-advancing consumer advances past the whole batch on the next
  read rather than re-reading the same undecodable entries indefinitely

#### Scenario: Publish still rejects malformed salience

- **WHEN** an event with a missing or out-of-range salience is published
- **THEN** the publish is rejected, unchanged by this resilience requirement
