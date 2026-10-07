## ADDED Requirements

### Requirement: Unreadable intent-log lines count as spoken evidence
The divergence assessment's spoken-evidence check SHALL treat an intent-log or corpus line that cannot be decrypted or parsed as evidence that the being has spoken, so the voice arm votes diverged rather than abstaining.

#### Scenario: A log holding only an undecryptable line
- **WHEN** the only line in the intent log is an envelope that fails authentication
- **THEN** the voice arm votes diverged and the being is assessed as diverged
