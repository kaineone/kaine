## ADDED Requirements

### Requirement: Organ decoding carries a sequence repetition penalty

Speak and think requests SHALL carry the DRY penalty fields `dry_multiplier`, `dry_base`, `dry_allowed_length` and `dry_penalty_last_n` from `[language]` when `dry_multiplier` is above 0, and SHALL carry none of them when it is 0 or absent. The in-process `llama_cpp` backend SHALL ignore the penalty.

#### Scenario: Penalty sent with the shipped config
- **WHEN** the language module realizes a think intent with `dry_multiplier = 0.8`, `dry_base = 1.75`, `dry_allowed_length = 2` and `dry_penalty_last_n = 2048`
- **THEN** the request body carries those four fields with those values

#### Scenario: Penalty off leaves the body unchanged
- **WHEN** `dry_multiplier` is 0 or absent
- **THEN** the request body is identical to the body built without the penalty

### Requirement: Thought has its own token cap

Think intents SHALL be generated with at most `think_max_tokens` tokens when it is set, and with `max_tokens` when it is absent; speak intents SHALL use `max_tokens`.

#### Scenario: Think and speak caps differ
- **WHEN** `max_tokens = 512` and `think_max_tokens = 128`
- **THEN** a think request has `max_tokens` 128 and a speak request has `max_tokens` 512

### Requirement: Degenerate text is cut at a sentence boundary

With `sentence_cut` true, the generated text SHALL be cut before its first sentence of at least three words that repeats an earlier sentence verbatim (ignoring case and whitespace), and a text the server stopped at the token cap SHALL be cut back to its last complete sentence when it has one. The cut text SHALL be what is published, logged and returned, the intent-log record SHALL carry `extra.text_cut` with the reason and the generated length, and no log line SHALL carry the text.

#### Scenario: A looping thought is cut at the first repeat
- **WHEN** the organ returns "I do not know how I feel. I do not know what I am thinking about. I do not know what I am thinking about."
- **THEN** the published and logged text is "I do not know how I feel. I do not know what I am thinking about." and `extra.text_cut.reason` is `"repeated_sentence"`

#### Scenario: A capped text ends at its last sentence
- **WHEN** the server reports `finish_reason` `"length"` for "I am here. I feel the"
- **THEN** the published text is "I am here." and `extra.text_cut.reason` is `"token_cap"`

#### Scenario: Cut off leaves the text unchanged
- **WHEN** `sentence_cut` is false or absent
- **THEN** the published text equals the organ's reply

### Requirement: The individuation probe keeps its conditions

`probe_request()` SHALL carry no DRY penalty and the probe's own `max_tokens`, its reply SHALL not be cut, and `probe_conditions()` SHALL be unchanged by the decoding keys.

#### Scenario: Probe request unaffected by decoding keys
- **WHEN** the language module is built with the shipped DRY values, `think_max_tokens` and `sentence_cut`
- **THEN** `probe_request()` returns a request with no DRY penalty and the passed `max_tokens`, and `probe_conditions()` equals that of a module built without them
