## ADDED Requirements

### Requirement: The pair builder skips identity leakage
The voice-alignment pair builder SHALL build no pair from an intent-log record whose `extra.identity_leak` is true. Such a record SHALL count as scanned and not as usable.

#### Scenario: A marked record
- **WHEN** the log holds one marked and one unmarked record that would each give a pair
- **THEN** the builder returns only the unmarked record's pair
