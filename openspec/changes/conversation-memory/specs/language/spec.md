## ADDED Requirements

### Requirement: The heard buffer extends the user turn
While conversation memory is enabled, the language module SHALL build the attributed heard user turn of every voice and comprehension request from the heard buffer, oldest first, with the current coalition's heard events last. Each quote SHALL be sanitized as today's heard quotes are. Each held utterance SHALL be attributed as "Someone else said a moment ago, in their words and not mine: ...". The logged heard turn SHALL carry the placeholder for every held utterance.

#### Scenario: The organ can answer a follow-up
- **WHEN** the operator asks a question, the entity answers, and the operator says "and the other one?" within 30 s
- **THEN** the request for the next reply holds both of the operator's utterances as attributed heard words

### Requirement: Comprehension requests are logged without their text
Each comprehension and episode request SHALL write an intent-log record with `mode = "comprehension"`, the logged prompt with heard speech redacted, the timings, the token counts, `generated_text = ""` and `extra.comprehension` holding the overlap guard's counts. Every builder of training pairs from the intent log SHALL skip records of that mode.

#### Scenario: No gist in the intent log
- **WHEN** a comprehension request returns a gist
- **THEN** the intent-log record holds no part of the gist and no voice-alignment pair is built from it

### Requirement: Persisted own utterances pass the overlap guard
While conversation memory is enabled, the language module SHALL pass `generated_text` through the overlap guard before writing an `external` or `internal` intent-log record. The published and spoken text SHALL be unchanged.

#### Scenario: An echo is masked in the log but spoken as said
- **WHEN** the entity repeats six consecutive heard words aloud
- **THEN** the vocal module receives the text as generated and the intent-log record holds `(their words)` in place of the run

### Requirement: The layout digest covers conversation memory only when it is enabled
`layout_digest()` SHALL include the comprehension lead headings, the held-utterance attribution and the episode-notes phrase if and only if conversation memory is enabled. The individuation probe SHALL therefore report changed conditions when the setting changes.

#### Scenario: Enabling conversation memory changes the digest
- **WHEN** conversation memory is enabled
- **THEN** `layout_digest()` differs from its value with conversation memory disabled
