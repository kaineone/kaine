# Design — unify inference on Unsloth Studio

## Context

Two model backends run today. The runtime path (Lingua organ + A/B baseline)
talks to **Ollama**; the sleep-cycle trainer talks to **Unsloth Studio** through
the out-of-process subprocess bridge. Studio has since become a full local
inference server (OpenAI-compatible `/v1`, `llama.cpp` backend, GGUF). Since
Studio is already required on CUDA hosts for training, serving inference from it
too lets us retire Ollama as a required dependency.

This is over-HTTP, so the Python/torch ABI incompatibility that forced the
out-of-process *trainer* bridge is **irrelevant here**: KAINE calls the backend
over a socket, exactly as it calls Ollama today. No in-process import of Studio's
env is introduced.

## Current coupling (the surface this change touches)

| Component | File:line | Today | Ollama-specific? |
|---|---|---|---|
| Organ inference | `lingua/client.py:129` `OllamaChatClient` | `POST /api/chat` + `think` flag | **yes** |
| Organ inference (alt, present but unused) | `lingua/client.py:47` `OpenAIChatClient` | `POST /v1/chat/completions` | no |
| A/B baseline | `evaluation/ab_divergence.py:75` | `POST /api/chat` + `think` | **yes** |
| GPU preflight: list resident | `cycle/preflight.py:125` | `GET /api/ps` | **yes** |
| GPU preflight: idle-unload | `cycle/preflight.py:136` | `POST /api/generate {keep_alive:0}` | **yes** |
| Wizard model discovery | `setup/__main__.py:51` | `GET /api/tags` | **yes** |
| Dependency spec | `setup/dependencies.py:66` | `DepSpec(name="ollama", port=11434, …)` | **yes** |
| Health probe | `nexus/health.py:588` | `GET /v1/models` | no (already generic) |

The health probe is already backend-neutral. Everything else routes through
Ollama-native endpoints and must move to `/v1` semantics.

## Decisions

### D1 — The contract is the endpoint, not the product
Canonicalize on **"an OpenAI-compatible local model server."** Unsloth Studio is
the reference implementation on CUDA (and is already required there for
training). The config keys point at a base URL; any conforming server
(`llama-server`, etc.) satisfies the contract. This keeps the headline ("drop
Ollama for Studio") while not hard-coding KAINE to a single product, and it is
the honest answer to the non-CUDA case below.

### D2 — Reasoning suppression moves to a portable mechanism
The organ runs with model CoT **off** (it is a voice; reasoning lives in Nous).
Today that is Ollama's top-level `think: false`. The portable equivalent on
`llama.cpp`/Studio's `/v1/chat/completions` is `reasoning_format` /
`chat_template_kwargs: {"enable_thinking": false}`. `ChatRequest.think` already
exists as the internal switch; only the wire mapping in `OpenAIChatClient`
changes. Keep the existing fail-safe: if the served model rejects the parameter,
retry without it (a non-thinking model needs nothing). **This is the one
correctness-critical item and gets a dedicated parity probe (see V1).**

### D3 — Single resident model simplifies the preflight
`llama-server`/Studio loads one model and keeps it resident for its lifetime;
there is no Ollama-style `keep_alive` idle eviction. Since the only model KAINE
wants resident *is* the organ (always the keep-model), the "evict non-organ idle
models" branch has nothing to act on. Reclamation for this backend becomes
**report-only**: the gate still measures per-device free VRAM, still names
foreign consumers, still preserves KAINE services, still never terminates
anything — it simply has no idle-evict lever, which is fine because there is
nothing idle to evict. This is a net simplification, not a regression.

### D4 — Parity extends from "same tag" to "same served file"
`abliterated-organ-default` already requires the organ and the A/B baseline to be
the *same model*, fail-closed on mismatch. Ollama expressed that as a shared tag.
Studio serves a concrete GGUF file. The shared identity therefore becomes the
**pinned GGUF (repo + quant + revision)**, fed identically to both. Recording it
as the research base-model covariate is unchanged in spirit; only the identifier
form changes (tag → GGUF id). The fail-closed check is preserved.

### D5 — Model sourcing requires no conversion
The organ `huihui_ai/qwen3.5-abliterated:9b` is Huihui-Qwen3.5-9B-abliterated;
a community GGUF exists at `mradermacher/Huihui-Qwen3.5-9B-abliterated-GGUF`.
Pin one quant (candidate: `Q4_K_M`) + revision and use it for organ **and**
baseline. Note: the Ollama tag and this HF GGUF are conversions of the same base
but are **not guaranteed bit-identical** — which is exactly why the invariant is
"same served file," satisfied by both pointing at the one pinned GGUF.

## Cross-vendor portability via the Unsloth toolchain

The wizard already routes the **trainer** by GPU vendor: CUDA → Unsloth Studio,
AMD/ROCm → **unsloth-core**, neither → no GPU trainer
(`first-run-wizard` "Hardware-aware sleep-trainer provisioning"). Inference now
follows the **same split**, so one hardware-aware path provisions both training
and inference per vendor:

- **CUDA** → Unsloth Studio (`llama.cpp`/`llama-server`), already required for
  training. Serves the pinned GGUF.
- **AMD/ROCm** → the **unsloth-core** install path (ROCm PyTorch wheels). Its
  inference is exposed through an OpenAI-compatible engine from that toolchain:
  **`llama.cpp` `llama-server` built for ROCm** — which serves the *same pinned
  GGUF*, so the served-file parity (D4) holds across vendors — or vLLM's OpenAI
  server (`vllm serve … --host … --port …`, GGUF support is more limited, so
  `llama-server` is preferred for parity). Both expose `/v1/chat/completions`.
- **No supported GPU (CPU/MPS/XPU)** → the operator points the same `chat_url` at
  any conforming OpenAI-compatible server.

Honest note: unsloth-core is a *training/runtime* library, **not itself an HTTP
server** — the OpenAI-compatible endpoint on ROCm is provided by `llama-server`
or vLLM that the unsloth-core toolchain pairs with. The spec says "the
unsloth-core toolchain's OpenAI-compatible inference engine" precisely to avoid
implying the library serves HTTP on its own.

Resolution (D1 holds): the requirement is an OpenAI-compatible local server on
every target; only the engine varies by vendor. KAINE stops *requiring* Ollama
and stops using its native API; it does not *forbid* pointing the endpoint at any
conforming server (Ollama's own `/v1` shim included). The config keys are the
single point of variation; the wizard names the backend per host.

## Why defer implementation

1. The first boot is imminent and runs on the **known-good Ollama stack**.
2. The cutover touches the **eval-parity invariant** (sovereignty-critical) and
   the **reasoning-suppression** path (correctness-critical) — both need a parity
   harness before they can be trusted, not a rushed pre-boot edit.
3. Studio-as-24/7-serving-daemon is **less battle-tested** than Ollama for a long
   unsupervised research run at 3.33 Hz. Prove it under load before depending on
   it for an ethically-scarce entity.

So: boot on Ollama, then land this behind a parity gate.

## Verification strategy

- **V1 — reasoning-suppression parity (gating).** Same prompt set through Ollama
  `/api/chat {think:false}` and Studio `/v1/chat/completions` with the portable
  suppression. Assert no visible CoT leaks and outputs are equivalent in
  structure. This is the acceptance gate for the swap.
- **V2 — organ↔baseline file parity.** Assert the organ and the A/B baseline
  resolve to the **same** served GGUF; assert fail-closed on a forced mismatch.
- **V3 — preflight behavior.** With a single-resident backend, the gate passes on
  ample headroom, reports (does not evict) on a short headroom, and **never
  terminates** any process; KAINE services preserved.
- **V4 — daemon soak.** Studio headless serves the organ continuously for a
  sustained run without leak/stall before the backend is declared default.
- **V5 — full suite green**; `openspec validate --strict`; import-boundary
  contracts intact (the backend is still reached only over HTTP).
