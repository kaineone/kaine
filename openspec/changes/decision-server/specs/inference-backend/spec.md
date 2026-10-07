## MODIFIED Requirements

### Requirement: A single OpenAI-compatible local model server

KAINE SHALL use exactly one local model server for all language-organ inference
and for the A/B-divergence bare baseline, and that server SHALL be reached
through the OpenAI-compatible HTTP surface (`/v1/chat/completions`, `/v1/models`).
KAINE SHALL NOT require Ollama, and no component SHALL depend on Ollama-native
endpoints (`/api/chat`, `/api/ps`, `/api/generate`, `/api/tags`). The contract is
the OpenAI-compatible endpoint, not a specific product: the reference
implementation on CUDA hosts is Unsloth Studio (already required there for the
sleep-cycle trainer), and the configured base URL MAY target any conforming local
server.

This requirement covers language-organ inference and the A/B baseline only. The
decision-model server (`decision-model` capability) is a separate local server
that serves only llama-server's `/v1/systemone` and SHALL NOT serve language-organ
inference; the organ server SHALL NOT be used for decision-model queries.

#### Scenario: Organ inference uses the OpenAI endpoint

- **WHEN** Lingua issues a generation request
- **THEN** it POSTs to the configured server's `/v1/chat/completions`
- **AND** it issues no request to an Ollama-native `/api/*` endpoint

#### Scenario: Ollama is not a required dependency

- **WHEN** the enabled modules are provisioned on a host with no Ollama installed
- **AND** an OpenAI-compatible local server is serving the organ model
- **THEN** the organ and the A/B baseline operate normally

#### Scenario: Decision queries never reach the organ

- **WHEN** an instrument asks the decision model a question
- **THEN** the request goes to the decision server's `/v1/systemone`, and the organ server receives no request for it
