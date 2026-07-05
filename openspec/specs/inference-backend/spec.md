# inference-backend Specification

## Purpose
TBD - created by archiving change unify-inference-on-studio. Update Purpose after archive.
## Requirements
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

#### Scenario: Organ inference uses the OpenAI endpoint

- **WHEN** Lingua issues a generation request
- **THEN** it POSTs to the configured server's `/v1/chat/completions`
- **AND** it issues no request to an Ollama-native `/api/*` endpoint

#### Scenario: Ollama is not a required dependency

- **WHEN** the enabled modules are provisioned on a host with no Ollama installed
- **AND** an OpenAI-compatible local server is serving the organ model
- **THEN** the organ and the A/B baseline operate normally

### Requirement: Reasoning suppression is backend-portable

The language organ SHALL run with the served model's chain-of-thought
suppressed (the organ is a voice; reasoning lives in Nous). Suppression SHALL use
the OpenAI-compatible / `llama.cpp` mechanism (`reasoning_format` or the
`enable_thinking=false` chat-template keyword argument), NOT Ollama's native
`think` flag. When the served model does not support the parameter, the client
SHALL retry the request without it (a non-thinking model needs no suppression)
rather than fail.

#### Scenario: Thinking model is asked to suppress chain-of-thought

- **WHEN** the organ requests a generation from a hybrid-thinking model with
  suppression enabled
- **THEN** the request carries the OpenAI-compatible suppression parameter
- **AND** the returned text contains no visible chain-of-thought

#### Scenario: Non-thinking model rejects the parameter

- **WHEN** the served model rejects the suppression parameter
- **THEN** the client retries the request without it and still returns text

### Requirement: Organ and A/B baseline share one backend and one served model

The language organ and the A/B-divergence bare baseline SHALL be served by the
same backend and SHALL resolve to the **same served model file** (a pinned GGUF
identified by repository, quantization, and revision). When an explicit baseline
model is configured that differs from the organ's served model, configuration
loading SHALL fail closed with a clear error (the divergence measurement would be
meaningless otherwise). This extends the existing abliterated-organ eval-parity
from "same tag" to "same served file".

#### Scenario: Baseline derives the organ's served model

- **WHEN** no explicit baseline model is configured
- **THEN** the A/B baseline uses the same pinned GGUF as the organ

#### Scenario: Explicit mismatch fails closed

- **WHEN** an explicit baseline model is configured that differs from the organ's
  served model
- **THEN** configuration loading raises a clear error and the cycle does not boot

### Requirement: Backend portability across GPU vendors via the Unsloth toolchain

KAINE SHALL support non-CUDA GPU hosts through the **unsloth-core** install path,
mirroring the hardware-aware vendor split already used for the sleep-cycle
trainer (CUDA → Unsloth Studio; AMD/ROCm → unsloth-core; CPU/MPS → no GPU
acceleration). The model backend SHALL remain an **OpenAI-compatible local
server** on every target; only the engine that provides it varies by vendor:

- **CUDA** — Unsloth Studio (`llama.cpp`/`llama-server`).
- **AMD/ROCm** — the unsloth-core toolchain's OpenAI-compatible inference engine:
  `llama.cpp` `llama-server` built for ROCm (serves the same pinned GGUF, so the
  served-file parity holds) or vLLM's OpenAI server.
- **No supported GPU** — the operator MAY point the same configuration keys at
  any conforming OpenAI-compatible local server.

The configuration keys (e.g. `[lingua].chat_url`) SHALL be the single point of
variation: the organ and the A/B baseline target whatever server is provisioned
for the host. KAINE SHALL speak only the OpenAI-compatible surface and SHALL NOT
require Ollama on any target.

#### Scenario: AMD/ROCm host serves the organ via the unsloth-core path

- **WHEN** the host's GPU backend is `rocm` and the unsloth-core inference engine
  (ROCm `llama-server` or vLLM) is serving the pinned organ model on its
  OpenAI-compatible endpoint
- **THEN** the organ and the A/B baseline operate unchanged against `/v1`
- **AND** no Ollama-native endpoint is used

#### Scenario: Served-file parity holds across vendors

- **WHEN** the configured backend (Studio on CUDA, or the unsloth-core engine on
  ROCm) serves the pinned organ model
- **THEN** the organ and the A/B baseline resolve to the same served model on
  that host

