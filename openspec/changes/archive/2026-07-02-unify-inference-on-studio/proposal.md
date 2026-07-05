## Why

KAINE currently runs **two** local model toolchains for two different jobs:

- **Ollama** serves the language organ (Lingua) and the A/B-divergence bare
  baseline at runtime.
- **Unsloth Studio** runs the sleep-cycle voice-alignment trainer (out-of-process
  subprocess bridge — see the `voice-alignment-training` capability).

Unsloth Studio is now itself a local inference server: an OpenAI-compatible
endpoint (`/v1/chat/completions`, `/v1/messages`, `/v1/models`) backed by
`llama.cpp`/`llama-server`, serving GGUF, multi-GPU, launchable headless
(`unsloth studio -H 0.0.0.0 -p <port>`). Verified against Unsloth's docs
(2026-06-16). Because Studio is **already a required dependency on CUDA hosts**
(for training), letting it also serve inference lets us **drop Ollama as a
required dependency** — one model backend instead of two. The win is operational,
not bytes: one service to install, health-check, gate, and configure; one fewer
external dependency in the wizard; one backend surface across Lingua, the eval
baseline, the GPU preflight, and the Nexus probes.

There is also live **spec/code drift** this change resolves. The `lingua` spec
already states *"Chat client uses Unsloth Studio's OpenAI endpoint by default"*
(`/v1/chat/completions`), and the code ships an `OpenAIChatClient`
(`kaine/modules/lingua/client.py:47`) — yet the module actually wires the
Ollama-native `OllamaChatClient` (`client.py:129`, `POST /api/chat` with the
`think` flag) instead. Both clients target `127.0.0.1:11434` (Ollama's port).
The spec and the code disagree on which backend is canonical; this change makes
them agree on one.

The chosen organ — `huihui_ai/qwen3.5-abliterated:9b` (Ollama tag) — is
compatible: Qwen3.5 is a first-class Studio architecture, and a GGUF of the exact
abliterated 9B exists (`mradermacher/Huihui-Qwen3.5-9B-abliterated-GGUF`), so no
weight conversion is required.

This is a **design-first proposal. Implementation is deferred** until after the
operator-supervised first boot (which proceeds on the current Ollama stack). The
cutover must not re-open the eval-parity invariant or introduce a less-proven
serving daemon right before an ethically-scarce boot.

## What Changes

- **One inference backend.** KAINE's canonical local model server SHALL be a
  single OpenAI-compatible endpoint. Ollama SHALL NOT be a required dependency.
  All organ inference and the A/B-divergence baseline SHALL use
  `/v1/chat/completions`; no component SHALL depend on Ollama-native `/api/*`
  endpoints (`/api/chat`, `/api/ps`, `/api/generate`, `/api/tags`).
- **Lingua** uses `OpenAIChatClient` as its sole production client; the
  `OllamaChatClient` is retired. The organ's reasoning/CoT suppression (today
  Ollama's native `think` flag) moves to the backend-portable mechanism
  (`llama.cpp` `reasoning_format` / the `enable_thinking=false` chat-template
  kwarg on `/v1/chat/completions`), with a fail-safe retry when the served model
  does not support it. Suppression remains load-bearing (the organ is a voice,
  not a reasoner).
- **The shipped organ** is specified as a **pinned GGUF** (repo + quant +
  revision) served by the backend, replacing the "Ollama-pullable tag" wording.
  The **same served model file** feeds both the organ and the A/B baseline
  (extends the existing abliterated-organ eval-parity from "same tag" to "same
  served file"; mismatch fails closed).
- **GPU preflight** generalizes its reclaim from "KAINE's own resident *Ollama*
  models" to "the inference backend's resident models." Because Studio/
  `llama-server` holds a **single resident model** (the organ — which is always
  the keep-model), there is nothing extra to idle-evict: reclamation becomes
  **report-only** for that backend. The gate still measures per-device headroom,
  still preserves KAINE services, and still **never terminates any process**.
- **First-run wizard / dependency provisioning** treats the local
  OpenAI-compatible server (Unsloth Studio on CUDA) as the model-backend
  dependency, detected by port and reused from the existing hardware-aware
  trainer-provisioning path. Ollama is removed from the required-dependency set.
  Model discovery moves from Ollama's `/api/tags` to `/v1/models` (the Nexus
  health probe already uses `/v1/models`).
- **Portability across GPU vendors via the Unsloth toolchain.** The backend is
  selected per vendor, mirroring the existing trainer split: CUDA → Unsloth
  Studio; AMD/ROCm → the **unsloth-core** toolchain's OpenAI-compatible inference
  engine (ROCm `llama.cpp` `llama-server`, which serves the same pinned GGUF so
  parity holds, or vLLM); no supported GPU → guide a conforming server. The
  contract is the **OpenAI-compatible endpoint**, and the config keys are the
  single point of variation — KAINE requires Ollama on no target.

## Impact

- Affected specs: **inference-backend** (new), **lingua** (modified),
  **gpu-preflight** (modified), **first-run-wizard** (modified).
- Affected code (implementation, deferred): `kaine/modules/lingua/client.py`,
  `kaine/modules/lingua/module.py`, `kaine/evaluation/ab_divergence.py`,
  `kaine/cycle/preflight.py`, `kaine/setup/__main__.py`,
  `kaine/setup/dependencies.py`, `kaine/nexus/health.py`, `config/kaine.toml`,
  `scripts/tier1_smoke.py`, and the corresponding tests.
- Non-goals: changing the cognitive architecture, the divergence metric's
  content-free contract, or the out-of-process trainer bridge. This is a backend
  swap behind stable interfaces.
