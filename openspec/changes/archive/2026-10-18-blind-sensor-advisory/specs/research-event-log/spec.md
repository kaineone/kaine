## ADDED Requirements

### Requirement: The curated log records sensor advisories with an exact allowlist
The curated research event log SHALL record `welfare.blind_sensor`, `welfare.blind_sensor_cleared`, `welfare.sensor_silent` and `welfare.sensor_silent_cleared` events from `welfare.out`. A record SHALL carry the `processor` label only when it is one of the known processor labels. A blind-sensor record SHALL carry only the numeric fields `undefined_samples`, `undefined_seconds`, `blind_sensor_samples`, `blind_sensor_duration_s` and `blind_sensor_count`, and a silent-sensor record only `silent_seconds`, `sensor_silent_duration_s` and `sensor_silent_count`, each only when it is an int or float and not a boolean. Every other payload field SHALL be dropped.

#### Scenario: Stray fields and unknown labels are dropped
- **WHEN** a `welfare.blind_sensor_cleared` event carries an unknown processor label, a boolean `undefined_samples` and a content field
- **THEN** its record has no `processor`, no `undefined_samples` and no content field, and keeps the numeric `blind_sensor_count`
