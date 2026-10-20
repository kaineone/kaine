## ADDED Requirements

### Requirement: The research log records only its own run
When the evaluation sidecar builds the curated research observer, the observer SHALL start each curated stream after the newest entry present when the observer starts, so entries a previous run published to the persisted streams are never recorded under the current run, and every entry published after the observer started is recorded. A stream that is empty at start SHALL be read from its head. When the newest-entry lookup fails, the observer SHALL start at the current millisecond and SHALL NOT read from the head.

#### Scenario: A restart does not replay the previous run
- **WHEN** the curated streams hold entries from a previous run and the observer starts
- **THEN** none of those entries is written to the log

#### Scenario: Entries after start are recorded
- **WHEN** an entry is published to a curated stream after the observer started
- **THEN** it is written to the log

#### Scenario: A failed lookup does not replay
- **WHEN** the newest-entry lookup raises at start
- **THEN** entries published before start are not written and entries published after start are
