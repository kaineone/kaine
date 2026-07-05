## MODIFIED Requirements

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
