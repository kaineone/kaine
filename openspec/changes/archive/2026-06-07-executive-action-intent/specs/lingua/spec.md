## ADDED Requirements

### Requirement: External speech is intent-driven, not self-triggered

Lingua SHALL produce external speech only in response to a `speak` intent
emitted by the executive action-selection step. Lingua SHALL NOT decide on its
own to respond to perceived input (e.g. a user transcription appearing in the
workspace): the decision to speak belongs to the executive, which is gated by
inhibition. Lingua realizes a `speak` intent via its existing `speak()` path,
using the intent's referenced conscious content as the prompt. A `think` intent
is realized via `think()` (internal speech).

#### Scenario: Lingua speaks when given a speak intent

- **WHEN** a `speak` intent is delivered to Lingua
- **THEN** Lingua produces one external-speech output via `speak()` on
  `lingua.external`

#### Scenario: Lingua stays silent on perceived input without an intent

- **WHEN** a user transcription appears in the workspace but no `speak` intent
  is issued (e.g. the snapshot was inhibited)
- **THEN** Lingua produces no external speech
