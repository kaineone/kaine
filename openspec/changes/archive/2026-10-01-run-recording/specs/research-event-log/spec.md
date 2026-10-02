## ADDED Requirements

### Requirement: External utterances are recorded locally, and inner speech never
When `[research_event_log.external_utterances].enabled` is true, the cycle SHALL record each `external_speech` event from `lingua.external`, with its text and timestamps, through the encrypted JSONL sink under `state/research/external_utterances/`. It SHALL NOT subscribe to `lingua.internal`, SHALL NOT record any `internal_speech` event, and SHALL NOT record `user_input`. The log SHALL NOT be export-eligible.

#### Scenario: An inner thought is not recorded
- **WHEN** Lingua publishes an `internal_speech` event while the log is enabled
- **THEN** nothing about it is written to the external-utterance log

#### Scenario: An utterance is recorded
- **WHEN** Lingua publishes an `external_speech` event while the log is enabled
- **THEN** its text and timestamps are written to the external-utterance log

### Requirement: What Nexus displays is recorded for each run
When `[research_event_log.nexus_record].enabled` is true, the cycle SHALL record every event on the streams Nexus displays, after the same privacy filter Nexus applies, through the encrypted JSONL sink under `data/nexus_record/`. The record SHALL contain nothing that Nexus's filtered feed does not contain. It SHALL NOT be export-eligible.

#### Scenario: The record matches the display
- **WHEN** an event on a displayed stream is published during a run with the record enabled
- **THEN** the record holds the same filtered payload the Nexus bridge sends

#### Scenario: Filtered content stays out
- **WHEN** an event carries a field the privacy filter removes
- **THEN** that field does not appear in the record
