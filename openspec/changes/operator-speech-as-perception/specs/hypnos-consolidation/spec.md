## ADDED Requirements

### Requirement: The ignition audit reports operator speech
When operator speech was heard in the audited window, the ignition audit SHALL compute the content-free counts `operator_speech_heard`, `operator_speech_accessed` (distinct heard utterances that won access at least once), `spoke_after_operator_speech` (accessed utterances followed by a realized `external_speech` within 30 s of entity time after their first access, before the next accessed one), `spoke_otherwise` and `operator_speech_access_share`, read from main-bus counts and labels only, and SHALL publish them as `sleep_readout.operator_speech` on `sleep_readout.out`, a stream that is not a workspace candidate stream and that no module consumes. The counts SHALL NOT be part of `sleep.ignition_audit` or the `sleep.sleep.completed` summary, which are published on `sleep.out` and can win access. When none was heard, nothing SHALL be published.

#### Scenario: Speech heard and answered once
- **WHEN** three operator utterances are heard, two win access, and the entity speaks 12 s after the first accessed one only
- **THEN** the readout reports heard 3, accessed 2, spoke after 1, and an access share of 2/3

#### Scenario: One utterance accessed on several ticks
- **WHEN** one operator utterance wins three consecutive broadcasts
- **THEN** it counts once as accessed, and its window starts at its first access

#### Scenario: No operator speech
- **WHEN** no operator transcription was heard in the window
- **THEN** no readout is published and the audit record is identical to one written without this requirement

#### Scenario: Film voices are not operator speech
- **WHEN** only media-channel transcriptions were heard
- **THEN** no readout is published

#### Scenario: The readout stays outside the entity
- **WHEN** a readout is published
- **THEN** it is on `sleep_readout.out` only, and neither `sleep.ignition_audit` nor `sleep.sleep.completed` carries its fields

### Requirement: The audit reads transcriptions only when speech-to-text is on
The sleep module SHALL read `audition.out` for the ignition audit only when `[audition].transcription_enabled` is true.

#### Scenario: Speech-to-text off
- **WHEN** the entity runs with `transcription_enabled = false`
- **THEN** the sleep module's audit cursors and serialized state are identical to a build without this requirement
