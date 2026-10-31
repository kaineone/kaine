## ADDED Requirements

### Requirement: The pair builder writes the shape the organ was served
The voice-alignment pair builder SHALL write each pair from a language-module intent-log record as an own-turn pair, without a user turn when the fixed cue was sent. It SHALL skip a record with a heard turn, a record marked `served_text_redacted`, and a record whose `think_sent` is not exactly false, and SHALL count each skip reason in its content-free phase result.

#### Scenario: A record with heard speech
- **WHEN** an intent-log record carries a heard turn
- **THEN** no pair is built from it and the heard-turn skip count rises by one

#### Scenario: A record served without the thinking flag
- **WHEN** a record's `think_sent` is null because the server rejected the flag
- **THEN** no pair is built from it and the thinking skip count rises by one

#### Scenario: A plain own utterance
- **WHEN** a record has no heard turn, is not redacted and has `think_sent` false
- **THEN** its pair has `own_turn` true and no `user_turn`
