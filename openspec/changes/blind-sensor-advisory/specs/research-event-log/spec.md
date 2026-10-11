## ADDED Requirements

### Requirement: The curated log records blind-sensor advisories with an exact allowlist
The curated research event log SHALL record `welfare.blind_sensor` and `welfare.blind_sensor_cleared` events from `welfare.out`. A record SHALL carry the `processor` label only when it is one of the known processor labels, and only the numeric fields `undefined_samples`, `undefined_seconds`, `blind_sensor_samples`, `blind_sensor_duration_s` and `blind_sensor_count`, each only when it is an int or float and not a boolean. Every other payload field SHALL be dropped.

#### Scenario: Stray fields and unknown labels are dropped
- **WHEN** a `welfare.blind_sensor_cleared` event carries an unknown processor label, a boolean `undefined_samples` and a content field
- **THEN** its record has no `processor`, no `undefined_samples` and no content field, and keeps the numeric `blind_sensor_count`
