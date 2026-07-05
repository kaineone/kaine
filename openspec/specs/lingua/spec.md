# lingua Specification

## Purpose
TBD - created by archiving change lingua. Update Purpose after archive.
## Requirements
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
The default `ChatClient` implementation SHALL be `OpenAIChatClient`, which POSTs
to the configured local server's `/v1/chat/completions` with an OpenAI-compatible
chat-completions request body. It SHALL be the sole production client; the
Ollama-native `/api/chat` client SHALL be retired. The organ's chain-of-thought
suppression SHALL be expressed through the OpenAI-compatible / `llama.cpp`
mechanism (`reasoning_format` / `enable_thinking=false` chat-template keyword
argument), with a fail-safe retry-without when the served model rejects it. The
client SHALL remain swappable via the `ChatClient` protocol so tests inject a
fake. The base URL SHALL be configurable (`[lingua].chat_url`) and SHALL default
to the local OpenAI-compatible server's `/v1` base; the default is
backend-agnostic (Unsloth Studio on CUDA hosts, any conforming server elsewhere).

#### Scenario: Default client targets the local OpenAI-compatible server
- **WHEN** `OpenAIChatClient()` is constructed with no overrides
- **THEN** its `base_url` property is the configured local server's `/v1` base
- **AND** generation requests are issued to `/v1/chat/completions`, never to an
  Ollama-native `/api/*` endpoint

#### Scenario: Chain-of-thought is suppressed portably
- **WHEN** the organ requests generation from a hybrid-thinking model with
  suppression enabled
- **THEN** the request carries the OpenAI-compatible suppression parameter
- **AND** if the served model rejects it, the client retries without it

#### Scenario: Custom client substitutes cleanly
- **WHEN** Lingua is constructed with a custom `ChatClient` that returns a canned
  response
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

### Requirement: Shipped language organ is an abliterated model

The shipped `config/kaine.toml` SHALL set `[lingua].model_id` to an abliterated
model — one whose refusal direction has been removed so the cognitive stack
(Eidolon values, Thymos, the workspace) governs behavior rather than the model's
baked-in refusals. The committed default SHALL be a publicly available abliterated
model served as a **pinned GGUF** (identified by repository, quantization, and
revision) by the local OpenAI-compatible backend. The **same served GGUF** SHALL
feed both the organ and the A/B-divergence baseline. Operators MAY override it
locally in `config/kaine.operator.toml`; that override SHALL itself be an
abliterated model.

#### Scenario: Shipped config ships an abliterated organ

- **WHEN** the committed `config/kaine.toml` is read
- **THEN** `[lingua].model_id` names an abliterated model (not a stock,
  refusal-conditioned one), expressed as a pinned GGUF identity

#### Scenario: Operator scales up locally

- **WHEN** an operator sets `[lingua].model_id` in `config/kaine.operator.toml`
- **THEN** the override is deep-merged over the shipped value

