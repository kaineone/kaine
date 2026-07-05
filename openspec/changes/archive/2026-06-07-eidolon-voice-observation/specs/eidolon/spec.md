## ADDED Requirements

### Requirement: The self-model observes the developing voice on both channels

Eidolon SHALL observe both internal and external speech and record the
developing voice in the self-model as lightweight per-utterance features. For
each observed utterance it SHALL record `{timestamp, channel, length,
word_count}` (channel is `internal` or `external`) into a capped
`voice_observations` buffer, and SHALL maintain an `external_speech_count`
alongside the existing `internal_speech_count`. Eidolon SHALL NOT persist the
raw utterance text in the self-model (only derived features). The
`voice_observations` buffer SHALL be capped and SHALL round-trip through the
self-model's JSON serialization with safe defaults for models saved before this
change.

#### Scenario: Internal and external utterances are observed with features

- **WHEN** an internal-speech utterance and an external-speech utterance are
  published
- **THEN** the self-model gains one `voice_observations` entry per utterance
  with its channel, length, and word_count
- **AND** `internal_speech_count` and `external_speech_count` each increase

#### Scenario: Raw text is not persisted

- **WHEN** a speech utterance is observed
- **THEN** the recorded observation contains derived features only (no raw
  utterance text)

#### Scenario: The voice buffer is capped

- **WHEN** more utterances are observed than the configured cap
- **THEN** `voice_observations` retains only the most recent cap entries

#### Scenario: Older self-models still load

- **WHEN** a self-model persisted before this change (no voice fields) is loaded
- **THEN** it loads with `external_speech_count = 0` and an empty
  `voice_observations`
