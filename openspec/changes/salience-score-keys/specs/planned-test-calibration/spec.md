## ADDED Requirements

### Requirement: The tone analysis joins on stream-qualified ids
The tone analysis SHALL join a tone event to a broadcast member on source, type and the stream-qualified id `<stream>:<entry_id>`, and SHALL refuse with `ToneAnalysisError` a tone event or broadcast member whose id has no stream. It SHALL refuse a broadcast whose members share an id.

#### Scenario: A tone event accessed through the cycle is found
- **WHEN** a tone event and a soma event with the same bus id on their own streams are read on one broadcast tick, the tone event's score reaches the threshold and the soma event's does not
- **THEN** the tone analysis finds the tone event accessed

#### Scenario: A bare id is refused
- **WHEN** a tone record's `entry_id` is `0-0`
- **THEN** `tone_events` raises `ToneAnalysisError`
