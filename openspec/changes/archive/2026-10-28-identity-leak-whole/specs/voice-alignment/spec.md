## ADDED Requirements

### Requirement: The pair builder skips every text that says what the entity is
The voice-alignment pair builder SHALL build no pair from an intent-log record whose `extra.identity_leak` or `extra.self_description` is true, so voice adaptation trains self-description in neither direction (paper section 3.5). Such a record SHALL count as scanned and not as usable.

#### Scenario: A self-description
- **WHEN** a record carries `extra.self_description = true`
- **THEN** the builder returns no pair for it
