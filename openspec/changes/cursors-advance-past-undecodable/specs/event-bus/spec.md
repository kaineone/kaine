## ADDED Requirements

### Requirement: Every cursor-advancing consumer reads with the last scanned id
Every consumer that keeps a cursor on a bus stream SHALL read with `read_entries` and SHALL advance its cursor to the returned last-scanned id whenever one is returned, whether or not any entry in the batch decoded. A consumer that stops partway through a batch SHALL advance only to the last entry it handled, so the entries after it are read on the next poll. It SHALL handle the decoded entries exactly as it would without undecodable ones. A batch that advanced the cursor without decoding any entry SHALL count as progress for the consumer's poll pacing, and SHALL NOT be treated as an event of any kind. Only one-shot readers that keep no cursor MAY use `read`.

#### Scenario: A module input survives a long undecodable run
- **WHEN** more undecodable entries than one read returns are written to a stream a consumer follows, followed by a decodable event
- **THEN** the consumer handles the decodable event

#### Scenario: A skipped entry is not an interaction
- **WHEN** Chronos reads a batch of user-input entries none of which decode
- **THEN** its cursor advances past them
- **AND** its time since the last interaction is not reset

#### Scenario: New code cannot reintroduce the stall
- **WHEN** code under `kaine/` outside the bus and the listed one-shot readers calls `bus.read(`
- **THEN** a test fails naming the file and line

#### Scenario: A consumer that stops early resumes where it stopped
- **WHEN** the welfare monitor detects a crossing partway through a batch and the run continues
- **THEN** its cursor stays at the crossing entry
- **AND** the remaining entries of that batch reach its trackers on later polls
