## ADDED Requirements

### Requirement: Failed realizations leave a content-free audit record
When Lingua fails to realize a `speak` or `think` intent because generation raises (other than cancellation), it SHALL write one `realization_failed` record to `lingua.internal` in the same record format as its utterances, whose payload contains only `mode` (the intent kind) and `reason_class` (the exception class name). The record SHALL NOT contain the prompt, generated text, triggering input or exception message.

#### Scenario: Language organ raises during a speak intent
- **WHEN** a `speak` intent is realized and the chat client raises `ConnectionError`
- **THEN** `lingua.internal` receives one record with type `realization_failed` and payload `{"mode": "speak", "reason_class": "ConnectionError"}`, and `lingua.external` receives nothing

#### Scenario: The sleep-time audit counts the failure
- **WHEN** Hypnos's ignition audit classifies the records read from `lingua.internal`
- **THEN** the failure is counted in `realization_failed_count` and not as a realization
