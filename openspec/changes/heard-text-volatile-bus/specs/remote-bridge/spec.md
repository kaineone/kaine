## ADDED Requirements

### Requirement: The transcript feed reads words from companion entries
The remote bridge's `/transcript` loop SHALL read the words of `external_speech` and `audition.transcription` events from their companion entries, and SHALL skip an event whose companion entry is missing. It SHALL write nothing to disk.

#### Scenario: A heard line
- **WHEN** an operator transcription's companion entry exists
- **THEN** a transcript client receives a `heard` line with its words

#### Scenario: A missing entry
- **WHEN** an `external_speech` event's companion entry is missing
- **THEN** no line is sent for it and no error is raised
