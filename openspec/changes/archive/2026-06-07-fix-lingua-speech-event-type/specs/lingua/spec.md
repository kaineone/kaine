## ADDED Requirements

### Requirement: Speech is published with a stable semantic event type

Lingua SHALL publish external speech with event type `external_speech` and
internal speech with event type `internal_speech`, on the `lingua.external` and
`lingua.internal` streams respectively. The event type SHALL be the semantic
speech type, not the stream name, so consumers (the conversation surface and
the evaluation observers) can filter on a stable type. The producer's type
SHALL match what those consumers filter on.

#### Scenario: speak publishes an external_speech event

- **WHEN** `Lingua.speak(...)` is awaited
- **THEN** the published event on `lingua.external` has type `external_speech`

#### Scenario: think publishes an internal_speech event

- **WHEN** `Lingua.think(...)` is awaited
- **THEN** the published event on `lingua.internal` has type `internal_speech`

#### Scenario: conversation and observers receive the speech

- **WHEN** Lingua publishes external speech
- **THEN** a consumer filtering on type `external_speech` (conversation router;
  A/B-divergence / proactive-audit / affect-correlation observers) receives it
