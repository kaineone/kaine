## ADDED Requirements

### Requirement: Two speech modes routed to distinct streams
Lingua SHALL expose two public methods: `async speak(prompt,
snapshot=None)` for external speech and `async think(prompt,
snapshot=None)` for internal speech. External speech SHALL publish a
`lingua.external` event to its `lingua.external` stream; internal
speech SHALL publish a `lingua.internal` event to its
`lingua.internal` stream. Internal speech SHALL NEVER be published to
`lingua.external` and SHALL NEVER be sent to TTS by any KAINE module.

#### Scenario: speak publishes only to external stream
- **WHEN** `Lingua.speak("hello")` is awaited
- **THEN** exactly one event appears on `lingua.external` and zero
  events appear on `lingua.internal`

#### Scenario: think publishes only to internal stream
- **WHEN** `Lingua.think("inner monologue")` is awaited
- **THEN** exactly one event appears on `lingua.internal` and zero
  events appear on `lingua.external`

### Requirement: Intent-expression log records every output
Every successful `speak` or `think` SHALL append one JSONL record to
the configured intent-expression log. Each record SHALL contain at
minimum `timestamp`, `mode` (`"external"` or `"internal"`),
`prompt`, `generated_text`, `model`, and (when a snapshot was
provided) `faithful_rendering` — the deterministic rendering of the
same snapshot via `kaine.faithful.FaithfulRenderer`. The
`faithful_rendering` field is the "chosen" side of the DPO pair
Hypnos will build in Phase 6.

#### Scenario: speak with snapshot logs faithful rendering
- **WHEN** `Lingua.speak("hello", snapshot=snap)` is awaited with a
  non-empty snapshot
- **THEN** the intent-expression log gains one JSONL record whose
  `faithful_rendering` equals `FaithfulRenderer().render_snapshot(snap)`

#### Scenario: log record carries mode and model
- **WHEN** both `speak` and `think` are awaited
- **THEN** the intent-expression log contains two records whose
  `mode` values are `"external"` and `"internal"` respectively, and
  both records carry a `model` field

### Requirement: Chat client uses Unsloth Studio's OpenAI endpoint by default
The default `ChatClient` implementation SHALL POST to
`http://127.0.0.1:11434/v1/chat/completions` with an OpenAI-compatible
chat-completions request body. The client SHALL be swappable via a
`ChatClient` protocol so tests inject a fake.

#### Scenario: Default client targets local Unsloth Studio
- **WHEN** `OpenAIChatClient()` is constructed with no overrides
- **THEN** its `base_url` property equals `"http://127.0.0.1:11434/v1"`

#### Scenario: Custom client substitutes cleanly
- **WHEN** Lingua is constructed with a custom `ChatClient` that
  returns a canned response
- **THEN** every `speak` and `think` call returns that canned text

### Requirement: Bus events carry the generated text and metadata
The published events SHALL include `text`, `mode`, `model`,
`prompt_length`, `latency_ms`, and (when present) `faithful_rendering`.
External-stream events carry the same shape as internal-stream events.

#### Scenario: External event payload shape
- **WHEN** `speak("hi")` is awaited
- **THEN** the published event on `lingua.external` has a payload
  containing at least the keys `text`, `mode`, `model`,
  `prompt_length`, `latency_ms`

### Requirement: No automatic model modification
Lingua SHALL NOT modify the underlying model in any way during
runtime. Abliteration, fine-tuning, and LoRA application are
operator-approved out-of-band actions, not Lingua responsibilities.

#### Scenario: Lingua does not invoke training APIs
- **WHEN** Lingua is initialized and used
- **THEN** no calls are made to the Unsloth training API or any
  model-modification endpoint

### Requirement: Default Lingua config and disabled-by-default
The repository SHALL ship a `[lingua]` block in `config/kaine.toml`
with default values for `chat_url`, `model_id`, `temperature`,
`max_tokens`, `request_timeout_s`, `intent_log_path`,
`baseline_salience`, and `alert_salience`. `[modules].lingua = false`
SHALL keep first boot from auto-registering Lingua.

#### Scenario: kaine.toml carries defaults
- **WHEN** an operator inspects `config/kaine.toml`
- **THEN** they find a `[lingua]` section with the documented keys
  and `[modules].lingua == false`
