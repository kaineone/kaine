## ADDED Requirements

### Requirement: The ignition audit reports operator speech
When operator speech was heard in the audited window, the ignition audit SHALL add the content-free counts `operator_speech_heard`, `operator_speech_accessed`, `spoke_after_operator_speech` (a realized `external_speech` within 30 s of entity time after accessed operator speech, before the next), `spoke_otherwise` and `operator_speech_access_share`, read from main-bus counts and labels only. When none was heard, the fields SHALL be absent.

#### Scenario: Speech heard and answered once
- **WHEN** three operator utterances are heard, two win access, and the entity speaks 12 s after the first accessed one only
- **THEN** the audit reports heard 3, accessed 2, spoke after 1, and an access share of 2/3

#### Scenario: No operator speech
- **WHEN** no operator transcription was heard in the window
- **THEN** the audit record is identical to one written without this requirement

#### Scenario: Film voices are not operator speech
- **WHEN** only media-channel transcriptions were heard
- **THEN** the operator-speech fields are absent

### Requirement: The audit reads transcriptions only when speech-to-text is on
The sleep module SHALL read `audition.out` for the ignition audit only when `[audition].transcription_enabled` is true.

#### Scenario: Speech-to-text off
- **WHEN** the entity runs with `transcription_enabled = false`
- **THEN** the sleep module's audit cursors and serialized state are identical to a build without this requirement
