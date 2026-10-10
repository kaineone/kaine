## ADDED Requirements

### Requirement: Time since the last interaction survives a restart as lived time
Chronos SHALL save the time since the last interaction (or that none has occurred) and, on restore, SHALL report time since the last interaction continuing from the saved value, so time the entity was not running is not counted. A snapshot that records only an interaction timestamp SHALL be restored no later than the current entity time.

#### Scenario: A restart does not reset the time alone to zero
- **WHEN** Chronos is saved 500 s after the last interaction and restored into a new run whose entity clock starts at 0
- **THEN** its next report gives a time since the last interaction of about 500 s
