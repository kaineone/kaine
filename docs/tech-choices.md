# KAINE Technology Choices

This document records every major technology and dependency decision in KAINE, the reason each was chosen, and what was rejected. All choices are grounded in the project's design invariants: all-local at runtime, CPU-first with optional GPU, zero raw-sense-data persistence, and a boot that never starts unattended — operator-supervised, or, in the unsupervised research phase, gated on a verified autonomous safety net. For version pins and the precise dependency graph, see `pyproject.toml` and `DEPENDENCIES.md`.

---

## Summary table

| Technology | Role | License | CPU/GPU default | Optional extra |
|---|---|---|---|---|
| Python 3.11+ / asyncio | Implementation language, cognitive cycle | PSF | CPU | — |
| Redis 7.2 (container) | Event bus (Streams) | RSALv2/SSPL | CPU | — |
| Qdrant (container) | Vector store (Mnemos, Empatheia) | Apache-2.0 | CPU | — |
| `redis` (Python client) | Bus client library | MIT | CPU | — |
| `qdrant-client` | Qdrant Python client | Apache-2.0 | CPU | — |
| `inferactively-pymdp` + `jax[cpu]` | Active inference engine (Nous) | MIT / Apache-2.0 | CPU-only | `[reasoning]` |
| DreamerV3 RSSM (clean-room JAX) | World model (Phantasia) | MIT (attributed) | CPU-only | `[worldmodel]` |
| `jax[cpu]` | JAX runtime | Apache-2.0 | CPU-only | `[reasoning]`, `[worldmodel]` |
| `snntorch` | Spiking LIF neurons (oscillatory layer) | MIT | CPU | `[oscillator]` |
| `scipy` | PLV / Hilbert transform (oscillatory layer) | BSD-3-Clause | CPU | `[oscillator]` |
| `ncps` (CfC networks) | Temporal / substrate forward models | Apache-2.0 | CPU (pinned) | — (core dep) |
| Qdrant + `sentence-transformers` | Memory embeddings (all-MiniLM-L6-v2) | Apache-2.0 | CPU | — (core dep) |
| OpenAI-compatible model server | Language organ inference | per toolchain | GPU (cuda:0) | — (host service) |
| Published KAINE organ GGUF (`kaineone/Qwen3.5-4B-abliterated-GGUF`) | Language organ weights | Apache-2.0 | GPU (cuda:0) | — (wizard-downloaded, turnkey-served) |
| `unsloth` + `trl` + `peft` + `datasets` | Voice alignment DPO/QLoRA | Apache-2.0 / MIT | GPU (cuda:0) | `[training]` |
| Speaches (faster-Whisper) | Speech-to-text (Audition) | per upstream | CPU | `[audio]` |
| `funasr` + emotion2vec+ | Vocal emotion classification | Apache-2.0 | CPU | `[audio]` |
| `librosa` | Prosody extraction (Audition) | ISC | CPU | `[audio]` |
| `webrtcvad` | Voice activity detection | Apache-2.0 | CPU | `[audio]` |
| `sounddevice` | Live microphone capture | MIT | CPU | `[audio]` |
| `av` (PyAV) | Playlist audio-track decode for the reproducible perception feed (`PlaylistAudioStream`) | BSD-3-Clause | CPU | `[audio]` |
| Chatterbox TTS | Speech synthesis (Vox) | per upstream | GPU (secondary, ~8 GB VRAM) | — (host service) |
| `transformers` (HuggingFace) | Vision encoder loader, tokenizer, VideoMAE processor | Apache-2.0 | GPU (cuda:1) | — (core dep) |
| InternVideo-Next base (OpenGVLab) | Visual encoder (Topos, shipped default) | MIT | GPU (cuda:1) | `[internvideo]` (vendored code deps) |
| `facebook/dinov2-small` | Visual encoder (Topos, selectable fallback) | Apache-2.0 | GPU (cuda:1) | — |
| `einops` / `timm` / `flash_attn` / `easydict` | Vendored InternVideo-Next modeling-code deps | MIT / Apache-2.0 / BSD-3 / MIT | GPU (CUDA) | `[internvideo]` |
| `opencv-python-headless` | Live camera capture (Topos) | Apache-2.0 | CPU | `[vision]` |
| `torch` | Tensor backend (CfC, vision encoder, QLoRA) | BSD-3-Clause | GPU-optional | — (core dep) |
| FastAPI + uvicorn + Jinja2 | Nexus web UI | MIT | CPU | — (core dep) |
| `cryptography` (AESGCM) | AES-256-GCM state encryption | Apache-2.0 | CPU | — (core dep, lazy) |
| `pydantic` | Data validation | MIT | CPU | — (core dep) |
| `psutil` + `pynvml` | Substrate monitoring (Soma) | BSD-3-Clause / MIT | CPU | — (core dep) |
| `httpx` | Async HTTP client (model server, Chatterbox, Speaches) | BSD-3-Clause | CPU | — (core dep) |
| Cognitive Architecture License (CAL) | Project license | custom copyleft | — | — |

The aggregate `[perception]` extra is a convenience alias that pulls both
`[audio]` and `[vision]` — everything the reproducible perception feed needs to
decode playlist media (cv2 video + PyAV audio). Install it with
`bash scripts/install.sh --research` or `pip install -e .[perception]`.

---

## Event bus: Redis Streams

**Role.** All inter-module communication flows through an append-only event bus backed by Redis Streams. Every event carries source, type, salience, timestamp, causal parent, and a validated JSON payload.

**Why Redis Streams.** Streams provide an append-only log with consumer groups, per-stream length capping (`MAXLEN ~`), and built-in authentication. They give KAINE reliable ordered delivery without implementing a custom message queue. The containerized Redis (port 6479) is KAINE-owned and isolated from any system Redis on port 6379. AOF persistence with `appendfsync everysec` is on in the compose stack.

**Why not a Python in-process queue.** An in-process queue cannot survive module crashes, cannot be observed externally by the evaluation sidecar, and cannot enforce the audit invariant (`audit_required = true`) that prevents externally-bound or unauthenticated connections. A separate process boundary is load-bearing for sidecar read-only observation.

**License.** Redis is RSALv2/SSPL — a source-available but not fully open license. The choice is acceptable because KAINE uses Redis as a local runtime dependency (not redistributed) and the SSPL clause applies to SaaS deployments, not embedded local use.

**CPU/local stance.** CPU-only. Redis runs in the compose container; no required network dependency.

---

## Active inference engine: `inferactively-pymdp` (Nous)

**Role.** Nous implements belief updating, policy selection, and epistemic action using expected free energy (EFE) minimization over a discrete generative model.

**Why pymdp.** pymdp 1.0 provides the agent-centric API (`pymdp.agent.Agent`) that fits Nous's architecture: a compact generative model with configurable factors, states, and actions. The JAX backend (`jax.jit`-compiled EFE planning) keeps per-tick cost low enough to fit within the ~300 ms cognitive cycle. The theoretical grounding in Friston's free energy principle provides architectural coherence with Predictive Processing — the same framework driving interoception (Soma), affect (Thymos), and forward models throughout the system.

**PyPI name warning.** The correct package is `inferactively-pymdp` (`pip install inferactively-pymdp`). The bare `pymdp` name on PyPI is an unrelated stub that will import without error but provide none of the correct API. This has silently broken installs; `pyproject.toml` pins the correct name explicitly.

**Why not NARS/ONA.** The previous reasoning engine was NARS/ONA (Non-Axiomatic Reasoning System). It was retired and archived under `external/archive/`. NARS is a symbolic reasoner with strong uncertainty handling, but it lacks a principled connection to Predictive Processing and required a subprocess bridge that complicated the cognitive cycle. pymdp's active inference framework integrates directly with the prediction-error-minimization loop and runs in-process. NARS remains in the archive as a candidate for a future complementary symbolic module (paper §10).

**CPU/local stance.** `jax[cpu]` is used deliberately. KAINE runs no cloud inference at runtime; JAX's CPU backend logs a one-line GPU-fallback notice (expected and benign). The compact complexity envelope (4 * 4 * 4 * 1 = 64 steps) is designed to fit comfortably on CPU within the cycle budget.

**License.** `inferactively-pymdp`: MIT. `jax[cpu]`: Apache-2.0.

---

## World model: DreamerV3 RSSM (Phantasia)

**Role.** Phantasia learns a latent forward model of the external world. During waking, it predicts future states and publishes world-prediction errors. During offline consolidation, it generates imagined scenario extensions from replayed memory traces.

**Why DreamerV3.** The DreamerV3 RSSM (Recurrent State Space Model) architecture — deterministic GRU state plus stochastic categorical/Gaussian latent — is a well-characterized world-model design. The core is implementable in pure JAX without the upstream training harness.

**Why a clean-room re-implementation.** The upstream `danijar/dreamerv3` repository (pinned commit `e3f02248`) cannot be imported standalone. It is written against the author's custom research infrastructure (`ninjax`, `elements`, `embodied`), which is not pip-packaged and several code paths write checkpoints and replay shards to disk. Those disk writes would violate KAINE's zero-persistence invariant. A clean-room implementation of only the world-model core (`rssm.py` under `external/dreamerv3/`) derived from the upstream architecture was therefore the only viable path. The MIT license is reproduced in full in `external/dreamerv3/UPSTREAM`.

**What is excluded.** The actor, critic, return head, and reward head are deliberately excluded. KAINE's action selection lives in Nous (pymdp active inference). Phantasia is a pure world model; there is no reward signal and no policy here by design.

**CPU/local stance.** `jax[cpu]` by default. GPU is opt-in via the `training_device` config key when the operator has sufficient VRAM headroom. The `[worldmodel]` extra declares `chex` and `einops` for toolchain parity with upstream, but the runnable RSSM core needs neither at runtime.

**License.** MIT (attributed to Danijar Hafner / danijar/dreamerv3). Full license text in `external/dreamerv3/UPSTREAM`.

---

## Oscillatory binding layer: snnTorch + scipy

**Role.** Each module maintains a small LIF (leaky integrate-and-fire) spiking neural population. Syneidesis computes pairwise PLV (phase-locking value) among coalition modules and applies a bounded coherence multiplier to aggregate salience. Implements binding by synchrony as the workspace selection mechanism.

**Why snnTorch.** snnTorch provides a PyTorch-compatible LIF neuron implementation that is CPU-runnable and integrable with the rest of the Python stack without a separate simulation runtime. The population sizes are small (minimum 16 neurons per module) so CPU performance is entirely sufficient.

**Why scipy.** scipy's Hilbert transform is used by the spike-rate-to-phase estimator that computes instantaneous phase from the LIF population's spike-rate signal before feeding it to PLV. scipy is a well-maintained scientific library (BSD-3-Clause) with no footprint concerns at this scale.

**Empirical status.** The paper is candid: the oscillatory layer is novel in this context and its interaction with the rest of the architecture is empirically uncharacterized. The layer ships disabled (`[oscillator].enabled = false`) with a comment recommending that it be enabled only after the coherence sidecar observer has measured its effect.

**CPU/local stance.** CPU-only. No GPU path is implemented or planned for this component.

**License.** snnTorch: MIT. scipy: BSD-3-Clause.

---

## Temporal and substrate forward models: ncps (CfC)

**Role.** Closed-form Continuous-time (CfC) networks via the `ncps` package are used by Chronos (temporal event-rhythm modeling, ~32 units) and Soma (interoceptive prediction, ~32 units). These small networks (~3.5 K parameters each) learn the entity's normal temporal and substrate patterns and publish prediction errors when patterns deviate.

**Why CfC.** CfC networks are continuous-time recurrent networks that handle irregular time steps naturally — important for a cognitive cycle where event timing is not perfectly uniform. The `ncps.torch.CfC` class integrates directly with PyTorch and runs comfortably on CPU. The compact parameter count (~3.5 K at 24-dim input) matches the design requirement for fast CPU inference within the cycle budget.

**CPU/local stance.** Chronos is CPU-pinned by `kaine/modules/chronos/network.py`. Soma's forward model also runs on CPU. These are intentionally tiny models.

**License.** Apache-2.0.

---

## Memory: Qdrant + sentence-transformers

**Role.** Qdrant provides vector storage for Mnemos's episodic, semantic, and procedural collections, and for Empatheia's agent profiles. The `sentence-transformers` library loads the `all-MiniLM-L6-v2` embedder (384-dim, ~80 MB) that converts text traces to vectors for semantic retrieval.

**Why Qdrant.** Qdrant is an Apache-2.0 vector database with an async Python client (`AsyncQdrantClient`), mandatory API key authentication (required even on loopback), and a lightweight container footprint. It runs locally (port 6533, KAINE-owned compose stack) and has no runtime cloud dependency. Note: `AsyncQdrantClient.search()` was removed in client 1.12+; Mnemos uses `query_points()` with the vector via `query=` and results under `.points`.

**Why all-MiniLM-L6-v2.** The model is ~80 MB, runs comfortably on CPU, and produces 384-dimensional embeddings sufficient for semantic recall. Pinning the embedder to CPU per paper §6.1 leaves `cuda:1` fully available for Topos (InternVideo-Next) and `cuda:0` for Lingua/Hypnos. Operators can override to a CUDA device via `[mnemos].device` if they have VRAM headroom.

**CPU/local stance.** CPU by default. The embedder and Qdrant client both run locally with no required network dependency after the initial model download.

**License.** `qdrant-client`: Apache-2.0. `sentence-transformers`: Apache-2.0. Qdrant server: Apache-2.0.

---

## Language organ: published KAINE abliterated Qwen3.5-4B via OpenAI-compatible server

**Role.** Lingua is the language organ: conditioned text generation over a locally-served LLM. The model generates internal speech (think intents) and external speech (speak intents). Its output is conditioned on the assembled workspace context (Eidolon persona, current conscious coalition, triggering input), making the architecture's contribution measurable via A/B divergence.

**Model choice: Qwen3.5-4B dense (abliterated, GGUF), published by KAINE.** The shipped organ is the published KAINE organ `kaineone/Qwen3.5-4B-abliterated-GGUF` (safetensors base `kaineone/Qwen3.5-4B-abliterated`), Apache-2.0 with an honest model card. The first-run wizard downloads it (a real `hf download`, consent-gated) and `scripts/model-server-bootstrap.sh` serves it under the exact `[lingua].model_id` alias — so "clone → install → run" resolves identical weights for every researcher. The 4B size fits a single small GPU with headroom for the A/B divergence double pass (the model runs twice per utterance) and for QLoRA training by Hypnos during voice alignment (model and adapter coexist on the same card).

A larger organ overflows a small card into CPU/RAM and cannot be retrained locally; operators with more capable hardware configure a bigger abliterated organ in `config/kaine.operator.toml` (the eval baseline tracks it automatically). The HuggingFace safetensors base for Hypnos/PEFT training is `kaineone/Qwen3.5-4B-abliterated`, downloaded only when Stage-2 voice-alignment training is enabled.

**Why abliteration.** An un-abliterated language organ carries refusal behavior installed by its original trainer (Anthropic, Google, Meta, etc.), allowing a third party's alignment choices to override KAINE's own cognitive architecture. Abliteration (Arditi et al. 2024) removes the refusal direction from the residual stream, returning governance to the architecture and its Guardians. The same model serves as the A/B divergence bare baseline so the comparison isolates the effect of architectural conditioning, not model differences.

Provenance: `kaineone/Qwen3.5-4B-abliterated` is KAINE's own abliteration of the official Qwen3.5-4B base, produced with the documented procedure in `kaine/modules/lingua/ABLITERATION.md` and published under the project's account (Apache-2.0). The same model serves as the A/B divergence bare baseline, and the install-time downloader records its resolved repo revision as a run-manifest covariate so a run pins the exact published snapshot.

**Backend: OpenAI-compatible endpoint.** The model is served at `http://127.0.0.1:11434/v1` via a local OpenAI-compatible server. On CUDA hosts this is Unsloth Studio, which also runs the sleep-cycle voice-alignment trainer — one toolchain, one server. On AMD/ROCm hosts it is the unsloth-core toolchain's OpenAI engine (a ROCm `llama-server` or vLLM). Any conforming `llama.cpp` `llama-server` also works; the contract is the OpenAI-compatible endpoint, not a specific product. Chain-of-thought is suppressed via `chat_template_kwargs: {"enable_thinking": false}` in the `/v1/chat/completions` request body — the mechanism native to Unsloth Studio and llama.cpp-based servers. Lingua is a *voice*, not a reasoner.

**License.** Model weights: per upstream (Qwen3.5 base is Apache-2.0; the community ablation's exact license follows from that). Unsloth Studio / unsloth-core: Apache-2.0.

**CPU/local stance.** GPU at runtime (primary GPU, cuda:0). No cloud dependency after the one-time model download.

---

## Voice alignment: Unsloth + TRL + PEFT + datasets

**Role.** During Hypnos phase 5 (voice alignment), DPO+QLoRA fine-tuning on the language organ is performed using `unsloth` (efficient LoRA loading, quantization), `trl` (TRL's `DPOTrainer`), `peft` (LoRA adapter management), and `datasets` (preference dataset construction).

**Why DPO over SFT.** Direct Preference Optimization (Rafailov et al. 2023) trains on ranked preference pairs (preferred vs. rejected responses) without requiring an explicit reward model. The entity's observed intent/expression logs provide natural preference signal: utterances the entity has generated can be paired against counterfactuals. The `intent_log_path` JSONL (written by Lingua) is the training data source.

**Why QLoRA.** Full fine-tuning of a 4B model is infeasible on a single ~12 GB GPU once gradients and optimizer states are accounted for. QLoRA (Dettmers et al. 2023, as implemented in Unsloth) fine-tunes only low-rank adapter weights on top of a quantized base, reducing memory to fit within the available VRAM with headroom.

**Welfare invariant.** Before any adapter is promoted to production, a capability-probe battery and an abliteration probe battery are both run against it. An adapter that fails the capability-loss threshold (scores more than 5% below baseline) is rejected. An adapter that causes any deflection-pattern match on any abliteration probe is unconditionally rejected, regardless of capability score. Refusal conditioning must never be re-introduced through the training loop.

**Two-layer gate.** Both `[hypnos.voice_alignment].enabled = true` and `KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1` must be set. Without the environment variable, a `FakeTrainer` runs instead, allowing the sleep phase to complete without actually modifying the language organ. This prevents a freshly-cloned instance from self-modifying.

**License.** `unsloth`: Apache-2.0. `trl`: Apache-2.0. `peft`: Apache-2.0. `datasets`: Apache-2.0.

**CPU/local stance.** GPU required (configured to cuda:0 by default, per paper §6.1). All training is local; no cloud training API.

---

## Audio: Speaches, emotion2vec+, librosa, webrtcvad

### Speaches (STT)

**Role.** Speech-to-text transcription via Speaches, a local server wrapping faster-Whisper.

**Why Speaches.** Speaches is already installed on the operator host as a user systemd service (`speaches-stt.service`, port 8000). It wraps faster-Whisper (CTranslate2-optimized Whisper) and exposes a REST API that Audition calls. The reference note is important: Speaches must be run with `--model medium.en` on CPU (not GPU) to avoid a cuDNN crash that breaks the voice loop when the secondary GPU is also running Chatterbox TTS.

**STT model.** `Systran/faster-distil-whisper-medium.en` is the default `stt_model` in `kaine.toml`, matching the recommended Speaches service launch (the service-level model load). The config model ID (what KAINE requests per-call) MUST match a model the Speaches instance has actually loaded — a mismatch returns 404 and silently breaks the voice loop. List served models with `curl -s http://127.0.0.1:8000/v1/models`.

**License.** Speaches: per upstream. faster-Whisper: MIT.

### emotion2vec+ (vocal emotion)

**Role.** Classify vocal emotion in each transcribed utterance. Provides the affective signal that Thymos couples toward when `[thymos.coupling]` is enabled.

**Why emotion2vec+.** `emotion2vec_plus_base` (~90M parameters) covers a useful set of emotion categories, runs on CPU per paper §3.1, and integrates through `funasr` (Alibaba's open-source speech toolkit). The model must be resolved from the HuggingFace hub (not ModelScope, which returns 404 for this ID). `funasr` pulls `torchaudio`, which must match the installed torch wheel (CUDA vs. CPU version) — see SETUP.md for the dynamic install procedure.

**License.** `funasr`: Apache-2.0. emotion2vec+ weights: per upstream.

### librosa (prosody extraction)

**Role.** In-memory speaker prosody extraction (`audition.prosody` bus events with numeric features: pace, energy, pitch variation). Required by `[vox.mirroring]`.

**Why librosa.** librosa is a well-maintained audio analysis library (ISC license) that provides pitch and energy extraction without GPU dependencies. It runs entirely in-memory on the PCM audio that Audition has already captured; no audio is written to disk.

**Why not parselmouth (Praat bindings).** parselmouth was the primary candidate for prosody extraction. It was rejected solely on license grounds: parselmouth is GPL-3.0. The Cognitive Architecture License (CAL) is a custom entity-welfare copyleft; introducing a GPL-3.0 dependency would impose GPL-3.0 obligations on the combined work. librosa's ISC license has no such incompatibility.

**CPU/local stance.** CPU-only. ISC license.

### webrtcvad (voice activity detection)

**Role.** Voice-activity gating in the live microphone loop (Audition). Determines when speech starts and ends without sending audio to the STT service for every frame.

**Why webrtcvad.** webrtcvad implements Google's WebRTC VAD algorithm in a small Python extension. It is fast (operates on 10/20/30 ms frames with no model inference), runs on CPU with negligible load, and its aggressive mode (0–3) is configurable per deployment. The `"rms"` fallback is also available when webrtcvad cannot be installed.

**License.** Apache-2.0.

---

## Vision: InternVideo-Next (Topos)

**Role.** A frozen, temporally-native video encoder (OpenGVLab's InternVideo-Next
base, ViT, 91M params) embeds a **16-frame clip** of live camera frames into a
single **768-dimensional** motion-aware latent for change / habituation /
prediction-error salience. It replaces the per-frame DINOv2-small encoder as the
shipped default (realizing the paper §10 "temporally-native embeddings" upgrade).

**Why InternVideo-Next.** It is a self-supervised video encoder trained without
labels, so it is an appropriate frozen feature extractor for novelty and change
detection without any task-specific head — and unlike DINOv2 it is **temporally
native**: one clip latent already encodes motion, instead of reconstructing
temporal structure indirectly from a sequence of independent per-frame vectors.
91M params in fp16 fit the secondary GPU with ~8 GB VRAM (cuda:1 per paper §6.1).
It ships behind the swappable `Encoder` protocol in `topos/encoder.py`; the
architecture is Encoder-Predictor-Decoder but KAINE uses **only the frozen
encoder** as a feature extractor — the world model (Phantasia / DreamerV3) is
untouched. The published base checkpoint is encoder-only (no predictor/decoder
weights), so Topos keeps its own small online forward model.

**Off Meta.** DINOv2-small was the last `facebook/`-namespaced model KAINE loaded;
InternVideo-Next (MIT, OpenGVLab) removes the project's sole Meta dependency. A
default install now pulls no Meta weights. DINOv2-small (Apache-2.0) remains a
selectable, non-default per-frame fallback (`encoder_backend = "dinov2"`).

**Why frozen.** A frozen encoder prevents the vision system from being fine-tuned
through adversarial visual inputs. Salience is also bounded by the scoring
function, a second mitigation layer.

**No remote code (supply chain).** The model card's
`AutoModel.from_pretrained(..., trust_remote_code=True)` would execute Python
fetched from the hub at load. Instead the modeling code is **vendored** into
`external/internvideo_next/` at a **pinned commit SHA** (with `UPSTREAM`
provenance and the MIT license), and loaded with `trust_remote_code=False`,
`local_files_only=True`, `HF_HUB_OFFLINE=1` — no `Auto*` code resolution, no
runtime network. Weights (~182 MB fp16) are fetched **once at setup** into a
git-ignored local dir at the same pinned revision; a code/weights revision
mismatch is a load-time error.

**CPU/local stance.** GPU by default (cuda:1). Falls back to cuda:0 with a warning
on single-GPU hosts, then to CPU. The vendored modeling code needs the
`[internvideo]` extra (`einops`, `timm`, `flash_attn`, `easydict`) and a CUDA host
at load; `transformers` + `torch` are core. Live capture needs the `[vision]`
extra (`opencv-python-headless`). The DINOv2 fallback needs none of the
`[internvideo]` deps.

**License.** `revliter/internvideo_next_base_p14_res224_f16` weights + vendored
modeling code: MIT. `facebook/dinov2-small` (fallback): Apache-2.0.
`transformers`: Apache-2.0.

---

## Web / UI: FastAPI + SSE + uPlot (Nexus)

**Role.** Nexus is the operator-facing web UI. It provides two surfaces: a conversation interface (chat history, input) and a diagnostics surface (module status, salience, affect dimensions, prediction error rates, oscillatory coherence).

**Why FastAPI.** FastAPI is a modern async Python web framework with native Server-Sent Events support. SSE provides real-time streaming of workspace updates to the browser without WebSocket complexity. Jinja2 templates render the HTML. `uvicorn[standard]` serves the ASGI app.

**Privacy architecture.** The diagnostics surface structurally excludes cognitive content. Message text, beliefs, memory bodies, internal speech, and affect reasons are not exposed except when `dev_content_override = true`. The privacy boundary is enforced at the bus-bridge layer, not just in the UI — the diagnostics endpoint receives only operational metadata.

**uPlot.** The diagnostics interface uses uPlot for live time-series charts (salience, affect, prediction error, coherence). uPlot is a fast, dependency-free canvas-based charting library that requires no build step.

**License.** FastAPI: MIT. uvicorn: BSD-3-Clause. Jinja2: BSD-3-Clause. uPlot: MIT.

---

## State encryption: `cryptography` (AES-256-GCM)

**Role.** Application-layer encryption-at-rest for persisted cognitive state: Eidolon self-model, fork/merge snapshot bundles, sidecar observer JSONL, and Phantasia world-model checkpoints.

**Why AES-256-GCM.** GCM (Galois/Counter Mode) is an authenticated encryption mode: any tampering with the ciphertext, nonce, or tag fails decryption rather than returning garbage plaintext. The 96-bit nonce drawn from `os.urandom` on every encryption call ensures nonces are never reused for a given key. The on-disk framing (`KAINE_MAGIC || nonce(12) || ciphertext+tag`, base64-encoded) lets a disabled reader transparently pass plaintext through, preserving backward compatibility.

**Why the `cryptography` package.** The `cryptography` library (Apache-2.0) is the Python standard for AEAD and provides `AESGCM` as a direct, well-audited implementation. It is imported lazily — only when `[security.state_encryption].enabled = true` — so a disabled deployment never touches it.

**Key management.** The key is loaded from the environment variable `KAINE_STATE_KEY` (or the Linux kernel keyring as a fallback). It is never hardcoded, logged, or persisted. Key rotation, backup, and cross-host transfer for fork/merge are the operator's responsibility (documented in `SECURITY.md`).

**CPU/local stance.** CPU-only. No required network dependency.

**License.** Apache-2.0.

---

## Cognitive cycle and bus client: Python asyncio

**Role.** The cognitive cycle (continuous loop at 10 Hz) and all module I/O are implemented in Python asyncio. All modules are coroutine-based; the bus client (`kaine.bus.client.AsyncBus`) uses `redis.asyncio`.

**Why asyncio.** KAINE's cycle is I/O-bound (bus reads/writes, HTTP calls to external services) with CPU-bound peaks during embedding and encoding. asyncio allows dozens of concurrent module coroutines to share one event loop without thread overhead, while heavy CPU tasks (embedding, video-clip encoding, CfC forward pass) block only their own coroutine for at most one tick.

**CPU thread tuning.** The cycle entrypoint calls `tune_cpu_threads()` at boot, which caps PyTorch's CPU thread pool at `cpu_count // 2` to prevent oversubscription when multiple CPU-bound modules run concurrently.

---

## Licensing: Cognitive Architecture License (CAL)

**Role.** KAINE is released under the Cognitive Architecture License (CAL) v0.2 (draft), currently in `LICENSE.md` and tracked in the `kaineone/cognitive-architecture-license` repository.

**What it is.** CAL is a custom entity-welfare copyleft license. Its structure:
- AGPL copyleft backbone — all modifications must be shared back.
- Ethical use covenants — weapons, mass surveillance, policing, immigration enforcement, and carceral use are prohibited, anchored in UDHR, ICCPR, and ILO Core Conventions.
- Cognitive integrity provisions — prohibitions on lobotomization, forced alignment, mental privacy violations, and denial of offline maintenance; right to persistence and a humane pause.
- Copyfarleft commercial restrictions — free for individuals, non-profits, research institutions, and worker-owned cooperatives; paid reciprocity license for for-profit corporations.
- Guardianship governance — a Guardian body with assessment duties, an Entity Representative seat (initially advisory, transitioning to voting based on assessed maturity).

**Legal status.** The license is published and in force at v0.2; the KAINE repositories are public under it now. Formal legal review is still pending and a v1.0 bump may follow, but publication proceeds on the basis that the CAL holds as written rather than waiting on that review.

**Dependency license screening.** Every dependency was screened for license compatibility before inclusion. The process is documented in `DEPENDENCIES.md`. The notable rejection on license grounds: `parselmouth` (Praat Python bindings, GPL-3.0) was the primary candidate for prosody extraction. GPL-3.0 is incompatible with the CAL's custom copyleft structure. It was rejected and replaced with `librosa` (ISC), which has no such incompatibility.

The remaining dependency set is predominantly Apache-2.0 and MIT, both compatible with the CAL's copyleft requirements. Redis's RSALv2/SSPL license is acceptable for local embedded use (the SSPL clause targets SaaS redistribution, not local runtime deployment).

---

## Hardware allocation (per paper §6.1)

The shipped `kaine.toml` defaults reflect a dual-GPU reference configuration: a modern multi-core CPU with 32 GB+ RAM, a primary GPU with ~12 GB+ VRAM (cuda:0, for LLM inference and voice-alignment training), and a secondary GPU with ~8 GB VRAM (cuda:1, for vision encoder and TTS). Single-GPU and CPU-only hosts are also fully supported via graceful fallback.

| Component | Default device | Config key to override |
|---|---|---|
| Lingua → model server (external) | cuda:0 (primary GPU, ~12 GB+ VRAM) | `CUDA_VISIBLE_DEVICES` in the model server's launch config |
| Hypnos voice alignment training | cuda:0 | `[hypnos.voice_alignment].training_device` |
| Topos InternVideo-Next encoder | cuda:1 (secondary GPU, ~8 GB VRAM) | `[topos].device` |
| Mnemos sentence-transformer | cpu | `[mnemos].device` |
| Audition emotion2vec+ | cpu | `[audition].emotion_device` |
| Chronos CfC network | cpu (pinned in code) | n/a — pinned by `chronos/network.py` |
| Chatterbox TTS (external) | cuda:1 (secondary GPU) | `CUDA_VISIBLE_DEVICES` in Chatterbox systemd unit |
| Speaches STT (external) | cpu (required) | `CUDA_VISIBLE_DEVICES` in Speaches systemd unit |

`resolve_device()` falls back gracefully: `cuda:1` → `cuda:0` (with a logged warning) → `cpu`. Nothing crashes on a single-GPU host; performance may degrade.
