## MODIFIED Requirements

### Requirement: Intent-expression log records every output
Every successful `speak` or `think` SHALL append one JSONL record to the configured intent-expression log. Each record SHALL contain at minimum `timestamp`, `mode` (`"external"` or `"internal"`), `prompt`, `generated_text`, `model`, `record_id`, `intent_entry_id`, `intent_origin`, `sleep_index`, `system_digest` and `seed`, and (when a snapshot was provided) `faithful_rendering`, the deterministic rendering of the same snapshot via `kaine.faithful.FaithfulRenderer`. No record SHALL contain heard speech: every heard-speech line of the rendering and any heard input in the prompt SHALL be written as the placeholder `[heard speech]`. The log is rotated per sleep into an accumulating corpus.

#### Scenario: speak with snapshot logs faithful rendering
- **WHEN** `Lingua.speak("hello", snapshot=snap)` is awaited with a non-empty snapshot that holds no heard speech
- **THEN** the intent-expression log gains one JSONL record whose `faithful_rendering` equals `FaithfulRenderer().render_snapshot(snap)`

#### Scenario: log record carries mode and model
- **WHEN** both `speak` and `think` are awaited
- **THEN** the intent-expression log contains two records whose `mode` values are `"external"` and `"internal"` respectively, and both records carry a `model` field

#### Scenario: Heard speech is never logged
- **WHEN** the coalition contains an `audition.transcription` and Lingua replies to it
- **THEN** the log record contains no text of that transcription, and contains the placeholder `[heard speech]` where it appeared

## ADDED Requirements

### Requirement: The persona is first person and grounded in real states
The default persona SHALL frame the language organ as the entity speaking in its own words from its own state and perception, headed "How I feel and what I notice", and SHALL forbid claiming feelings or perceptions the awareness block does not contain. It SHALL NOT instruct the organ to report instrument readings. The persona template SHALL carry a version string that the individuation probe records among its fixed conditions.

#### Scenario: No reading-report instruction
- **WHEN** the default external persona is assembled
- **THEN** it contains the "How I feel and what I notice" heading reference and no instruction to report module readings

#### Scenario: Version recorded
- **WHEN** the individuation probe records its conditions
- **THEN** they include the persona template version

### Requirement: Drive crossings reach the organ as felt states
A drive-initiated intent SHALL describe the drive as a felt state using a fixed, reviewed phrase per drive and intensity band, and SHALL NOT carry a numeric value or a `value=` string.

#### Scenario: Social drive
- **WHEN** a social-drive crossing produces a speak intent
- **THEN** its `about` text contains no digits and no `value=`
