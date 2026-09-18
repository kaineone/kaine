## ADDED Requirements

### Requirement: Novelty scoring is O(1)
`NoveltyTracker.observe` SHALL use a hash-based counter of recent fingerprints so that lookup, scoring, and update are O(1) per event.

#### Scenario: Repeated fingerprint is counted in constant time
- **WHEN** the same fingerprint is observed 50 times within the window
- **THEN** each `observe` call completes in O(1) time

#### Scenario: Window eviction decrements the counter
- **WHEN** a fingerprint ages out of the window
- **THEN** its counter is decremented so the count always matches the window contents
