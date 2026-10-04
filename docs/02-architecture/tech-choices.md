# Technology choices

This page lists the runtime technologies and Python dependencies KAINE uses, why each was chosen, and the install extras that switch them on. Read it when you are choosing a deployment, checking a reproducibility claim, or adding a dependency. Exact pins are in `pyproject.toml`; licence screening is in [Licences](../appendix-c-licences.md). The architecture overview is in [Architecture](README.md), and module-by-module details live under [The modules](../09-modules/README.md).

The defaults below are the values in the shipped `config/kaine.toml`. With no profile selected, the loader also applies the base-thesis `thesis_test` profile, which chooses the module set and a few perception and voice settings.

---

## Summary table

The base install contains only the dependencies needed to start the bus and run the cycle: Python, `redis`, `pydantic`, `psutil`, `numpy`, `httpx`, and `cryptography`. Everything else is grouped into optional extras such as `[core]`, `[audio]`, `[vision]`, `[memory]`, `[reasoning]`, `[worldmodel]`, `[oscillator]`, `[training]`, `[nexus]`, `[internvideo]`, `[internvideo-flash]`, `[speech-edge]`, `[memory-edge]`, and `[nvidia]`. The `[perception]` extra is a convenience alias that pulls `[audio]` and `[vision]`.

| Technology | Role | License | Default device | Install extra |
|---|---|---|---|---|
| Python 3.11+ / asyncio | Language and cycle runtime | PSF | CPU | — |
| Redis 7.2 (container) | Event bus (Streams) | BSD-3-Clause | CPU | — |
| `redis` (Python client) | Bus client library | MIT | CPU | — |
| `pydantic` | Data validation | MIT | CPU | — |
| `psutil` | Substrate monitoring | BSD-3-Clause | CPU | — |
| `numpy` | Numerical stack | BSD-3-Clause | CPU | — |
| `httpx` | Async HTTP client | BSD-3-Clause | CPU | — |
| `cryptography` (AESGCM) | State encryption | Apache-2.0 | CPU | — (lazy) |
| `pynvml` | GPU monitoring | MIT | CPU | `[nvidia]` |
| Qdrant (container) | Vector store | Apache-2.0 | CPU | `[memory]` |
| `qdrant-client` | Qdrant client | Apache-2.0 | CPU | `[memory]` |
| sqlite-vec | Edge vector store | per upstream | CPU | `[memory-edge]` |
| `sentence-transformers` | Optional torch embedder | Apache-2.0 | CPU | `[memory]` |
| NumPy MiniLM embedder | Default text embedder; weights Apache-2.0 | LicenseRef-CAL-0.2 | CPU | built-in |
| `inferactively-pymdp` + `jax[cpu]` | JAX active-inference backend | MIT / Apache-2.0 | CPU | `[reasoning]` |
| NumPy Nous engine | Native active-inference backend | LicenseRef-CAL-0.2 | CPU | built-in |
| DreamerV3 RSSM (JAX/NumPy) | World model | MIT | CPU | `[worldmodel]` |
| NumPy Phantasia engine | Native world-model backend | LicenseRef-CAL-0.2 | CPU | built-in |
| `ncps` (torch CfC) | Torch CfC backend | Apache-2.0 | CPU | `[core]` |
| NumPy CfC | Default CfC backend | LicenseRef-CAL-0.2 | CPU | built-in |
| `torch` | Tensor backend | BSD-3-Clause | GPU-optional | `[core]` |
| `snntorch` | Spiking LIF neurons | MIT | CPU | `[oscillator]` |
| `scipy` | PLV / Hilbert transform | BSD-3-Clause | CPU | `[oscillator]` |
| OpenAI-compatible model server | Language organ inference | per upstream | GPU (`cuda:0`) | host service |
| llama.cpp server images | OpenAI-compatible endpoint | per upstream | GPU | host service |
| KAINE Qwen3.5-4B abliterated GGUF | Language organ weights | Apache-2.0 | GPU (`cuda:0`) | wizard download |
| `unsloth` + `trl` + `peft` + `datasets` | Voice-alignment training | Apache-2.0 / MIT | GPU (`cuda:0`) | `[training]` |
| Speaches (faster-Whisper) | Speech-to-text | per upstream / MIT | CPU | host service |
| sherpa-onnx + Moonshine | Edge STT | per upstream / MIT | CPU | `[speech-edge]` |
| sherpa-onnx + Kokoro | Edge TTS | per upstream; espeak-ng data is GPL-3.0-or-later | GPU / CPU | `[speech-edge]` |
| `funasr` + emotion2vec+ | Vocal emotion | Apache-2.0 / per upstream | CPU | `[audio]` |
| `librosa` | Prosody extraction | ISC | CPU | `[audio]` |
| `webrtcvad` | Voice activity detection | Apache-2.0 | CPU | `[audio]` |
| `sounddevice` | Microphone capture | MIT | CPU | `[audio]` |
| `av` (PyAV) | Playlist audio decode | BSD-3-Clause | CPU | `[audio]` |
| Chatterbox TTS | Speech synthesis | per upstream | GPU (`cuda:1`) | host service |
| `transformers` (HuggingFace) | Vision/tokenizer loader | Apache-2.0 | GPU (`cuda:1`) | `[vision]` |
| `opencv-python-headless` | Camera capture | Apache-2.0 | CPU | `[vision]` |
| InternVideo-Next base | Video encoder | MIT | GPU (`cuda:1`) | `[internvideo]` |
| `einops` / `timm` / `easydict` | Vendored InternVideo deps | various | CPU / GPU | `[internvideo]` |
| `flash_attn` | Accelerated InternVideo attention | various | GPU | `[internvideo-flash]` |
| DINOv2-small | Fallback video encoder | Apache-2.0 | GPU (`cuda:1`) | `[vision]` |
| FastAPI + uvicorn + Jinja2 | Nexus web UI | MIT / BSD-3-Clause | CPU | `[nexus]` |
| uPlot | Live charts in Nexus | MIT | CPU | `[nexus]` |
| Cognitive Architecture License (CAL) | Project license | LicenseRef-CAL-0.2 | — | — |

Install the research / perception bundle with `bash scripts/install.sh --research` or `pip install -e .[perception]`.

---

## Event bus

All inter-module events travel through Redis Streams. Each event carries source, type, salience, timestamp, causal parent, and a validated JSON payload. Every module publishes a stream named `<module>.out`; Lingua also publishes `lingua.internal` and `lingua.external`.

Redis Streams give KAINE an append-only log with consumer groups, per-stream length capping (`MAXLEN ~`), and built-in authentication. A separate process boundary matters: an in-process queue cannot survive a module crash, cannot be observed by the evaluation sidecar, and cannot enforce the audit invariant that refuses externally-bound or unauthenticated connections.

The containerized Redis runs on port 6479, isolated from any system Redis on 6379. AOF persistence with `appendfsync everysec` is on in the compose stack. The `redis:7.2-alpine` image is BSD-3-Clause; the SSPL/RSALv2 terms begin at Redis 7.4.

---

## Active inference engine

Nous implements belief updating, policy selection, and epistemic action by minimizing expected free energy over a discrete generative model. It supports two backends:

- JAX backend via `inferactively-pymdp` and `jax[cpu]`. The correct PyPI name is `inferactively-pymdp`; the bare `pymdp` package is an unrelated stub that imports silently but provides the wrong API.
- Native NumPy backend selected with `[nous].backend = "numpy"`. It needs neither JAX nor the `[reasoning]` extra.

pymdp's agent API fits a compact generative model, and the JAX path `jit`-compiles planning to stay within the cycle budget. The default complexity envelope is small (64 steps) and runs comfortably on CPU.

NARS/ONA is archived under `external/archive/` and is no longer used. It lacked a direct Predictive Processing foundation and required a subprocess bridge; active inference runs in-process and connects directly to the prediction-error loop across the system. See [Nous](../09-modules/nous.md) for module details and [The cognitive cycle](../08-cognitive-cycle/README.md) for timing.

---

## World model

Phantasia learns a latent forward model of the external world. The shipped default is `backend = "dreamerv3"` with `engine = "jax"`, `persist_weights = true`, and `training_enabled = true` in `config/kaine.toml`. A NumPy engine is also available.

The DreamerV3 RSSM — deterministic GRU state plus stochastic categorical/Gaussian latent — is a well-characterized world-model design. KAINE uses a clean-room implementation in `external/dreamerv3/` because the upstream repository cannot be imported standalone and writes replay shards and checkpoints to disk, which would violate the zero-persistence invariant. The actor, critic, return head, and reward head are excluded; action selection lives in Nous, so Phantasia stays a pure world model.

GPU training is opt-in via `training_device` when the operator has enough VRAM. The `[worldmodel]` extra pulls toolchain parity packages such as `chex` and `einops`, but the runnable RSSM core does not need them at runtime.

---

## Paired implementations

Four components have two implementations each: one ships, and the other is the reference. Both read and write the same state, so a being can move between them. A parity test holds them to the same results.

| Component | Ships by default | Reference | Selected by | Parity tests |
|---|---|---|---|---|
| CfC reservoir (Soma, Chronos) | NumPy | `ncps` on torch | `[soma].cfc_backend`, `[chronos].cfc_backend` | `tests/test_numpy_cfc.py` |
| Text embedder | NumPy MiniLM | `sentence-transformers` | `[embedding].backend` | `tests/test_text_embedding_numpy.py` |
| Active inference (Nous) | pymdp on JAX | NumPy engine | `[nous].backend` | `tests/test_numpy_aif_parity.py`, `tests/test_numpy_nous_engine.py` |
| World model (Phantasia) | JAX RSSM | NumPy RSSM | `[phantasia].engine` | `tests/test_rssm_numpy_parity.py` |

The base-thesis run uses the NumPy side for the CfC reservoirs and the embedder. Nous and Phantasia are off in the base thesis. For them the JAX side is the default, and the NumPy side exists for hosts without JAX, such as Termux.

CI installs every extra that both sides need and runs the whole suite on every pull request, so the parity tests run whenever either side changes. Changing which side ships changes the entity's computation, so it is a change of its own, never part of a refactor.

---

## Oscillatory binding layer

Each module keeps a small LIF spiking-neuron population (minimum 16 neurons). Syneidesis computes pairwise phase-locking value among coalition modules and applies a bounded coherence multiplier to aggregate salience. `snntorch` supplies a PyTorch-compatible LIF neuron, and `scipy` supplies the Hilbert transform used to estimate instantaneous phase.

The shipped `config/kaine.toml` disables it (`[oscillator].enabled = false`). Enable it only after the coherence sidecar observer has measured its effect.

---

## Temporal and substrate forward models

Chronos and Soma use Closed-form Continuous-time (CfC) networks. The default is the NumPy CfC in `kaine/cfc_numpy.py` via `cfc_backend = "numpy"` for both modules. A PyTorch alternative via `ncps.torch.CfC` is in the `[core]` extra.

CfC networks handle irregular time steps, which suits a cognitive cycle with non-uniform event timing. The networks are tiny (~3.5 K parameters at 24-dimensional input) and pinned to CPU in `kaine/modules/chronos/network.py`. Soma's fatigue and regulation integrate only prediction error beyond the learned expected-error band, not all cumulative error.

---

## Memory

Qdrant provides vector storage for Mnemos's episodic, semantic, and procedural collections and for Empatheia's agent profiles. It runs locally on port 6533 inside the KAINE compose stack and requires an API key even on loopback. The async client uses `query_points()` because `AsyncQdrantClient.search()` is not available in client 1.12+. sqlite-vec is available under `[memory-edge]` for edge deployments.

The shared text embedder defaults to the built-in NumPy MiniLM embedder in `kaine/text_embedding_numpy.py`. It runs `all-MiniLM-L6-v2` (384-dim, ~80 MB) from `model.safetensors`, `config.json`, and `vocab.txt` with a built-in WordPiece tokenizer. The optional `sentence-transformers` torch backend is selected with `[embedding].backend = "sentence_transformers"` and respects `[embedding].device`; the NumPy backend ignores `device` and stays on CPU.

See [Mnemos](../09-modules/mnemos.md) and [Empatheia](../09-modules/empatheia.md) for how these stores are used.

---

## Language organ

Lingua generates internal and external speech over a locally-served LLM. The shipped organ is `kaineone/Qwen3.5-4B-abliterated-GGUF` (safetensors base `kaineone/Qwen3.5-4B-abliterated`), Apache-2.0. The first-run wizard downloads it after operator consent, and `scripts/model-server-bootstrap.sh` serves it under the exact `[lingua].model_id` alias so every clone resolves the same weights.

Abliteration removes the residual-stream refusal direction installed by the original trainer, returning governance to KAINE's architecture and its Guardians. The same abliterated model is also the A/B divergence bare baseline, so any difference isolates architectural conditioning, not model differences.

The model is served through an OpenAI-compatible endpoint at `http://127.0.0.1:11434/v1`. On CUDA hosts the default path is Unsloth Studio, which also runs the sleep-cycle trainer. On AMD/ROCm or edge hosts the path uses llama.cpp server images or any conforming `llama-server`. Chain-of-thought is suppressed with `chat_template_kwargs: {"enable_thinking": false}` in the `/v1/chat/completions` request body. Lingua is a voice, not a reasoner.

A 4B training step (~9.8 GB) plus the loaded organ (~3 GB) do not fit together on a 12 GB card, so voice-alignment training time-shares `cuda:0` rather than running alongside inference. A larger organ overflows to CPU/RAM and cannot be retrained locally; operators with more VRAM can configure a larger abliterated organ in `config/kaine.operator.toml`.

Training can run in-process or via `trainer_backend = "subprocess"` / `"job_queue"` using the `kaine-trainer` container. The `hot_swap_mode = "organ_adapter"` option swaps only the LoRA adapter rather than the whole model. For the full sleep-phase procedure see [Voice alignment](../10-sleep/voice-alignment.md).

---

## Voice alignment

During Hypnos phase 5, voice alignment performs DPO+QLoRA fine-tuning on the language organ using `unsloth`, `trl`, `peft`, and `datasets`. Direct Preference Optimization trains on ranked pairs drawn from the entity's own intent log (`intent_log_path`).

Two gates must be open for real training: `[hypnos.voice_alignment].enabled = true` and `KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1`. Without the environment variable a `FakeTrainer` runs, so a freshly cloned instance cannot self-modify.

Before any adapter is promoted, a capability-probe battery and an abliteration-probe battery run against it. An adapter that drops capability more than 5% below baseline is rejected. An adapter that triggers any abliteration deflection pattern is rejected unconditionally.

---

## Audio

### Speech-to-text

Speaches wraps faster-Whisper and exposes a REST API on port 8000. The default model is `Systran/faster-distil-whisper-medium.en`, which must match a model the Speaches instance has actually loaded. A mismatch returns 404 and silently breaks the voice loop. List loaded models with:

```bash
curl -s http://127.0.0.1:8000/v1/models
```

Speaches must run with `--model medium.en` on CPU, not GPU, to avoid a cuDNN crash when the secondary GPU is also running Chatterbox TTS.

Audition also supports a NumPy log-spectral acoustic embedding in `kaine/modules/audition/acoustic.py` and, under the `[speech-edge]` extra, the sherpa-onnx Moonshine STT backend.

### Edge speech

`sherpa-onnx` is the edge speech backend. It runs the Moonshine STT model (MIT) and the Kokoro TTS model. The Kokoro archive bundles espeak-ng data that is GPL-3.0-or-later; that license is incompatible with the CAL, so any CAL-distributed build must handle that data as a license exception.

### Vocal emotion

emotion2vec+ (~90M parameters) classifies vocal emotion through `funasr`. It must resolve from the HuggingFace hub, not ModelScope. `funasr` pulls `torchaudio`, which must match the installed PyTorch wheel (CUDA versus CPU). See [Accelerators and PyTorch wheels](../03-hardware/accelerators.md) for wheel selection.

### Prosody

librosa extracts in-memory prosody (pace, energy, pitch variation) for `audition.prosody` bus events and `[vox.mirroring]`. librosa is ISC-licensed and has no GPL incompatibility; parselmouth (Praat bindings) is GPL-3.0 and incompatible with the CAL.

### Voice activity detection

webrtcvad gates the live microphone loop with negligible CPU load. Its aggressive mode (0–3) is configurable, and an `"rms"` fallback is available when webrtcvad cannot be installed.

---

## Vision

Topos uses OpenGVLab's InternVideo-Next base as its default encoder. A 16-frame clip becomes one 768-dimensional motion-aware latent used for change, habituation, and prediction-error salience. It is temporally native, so motion is encoded directly rather than reconstructed from independent per-frame vectors. The 91M-parameter fp16 checkpoint fits the secondary GPU (`cuda:1`).

The encoder is frozen and stays a feature extractor only; Phantasia remains the world model. To avoid executing remote hub code, the modeling code is vendored in `external/internvideo_next/` at a pinned commit and loaded with `trust_remote_code=False`, `local_files_only=True`, and `HF_HUB_OFFLINE=1`. Weights (~182 MB fp16) are fetched once at setup at the same pinned revision.

The default eager path needs no CUDA. The optional `[internvideo-flash]` extra adds `flash_attn` for accelerated attention. DINOv2-small (`facebook/dinov2-small`) remains a selectable per-frame fallback via `encoder_backend = "dinov2"`. Live camera capture needs the `[vision]` extra (`opencv-python-headless`).

---

## Web UI

Nexus is the operator-facing web UI. It is built with FastAPI, served by uvicorn, and renders HTML with Jinja2. Server-Sent Events stream real-time updates to the browser without WebSockets. uPlot draws the live charts.

The diagnostics surface structurally excludes cognitive content such as message text, beliefs, memory bodies, internal speech, and affect reasons. That boundary is enforced at the bus-bridge layer. Content is only exposed when `dev_content_override = true`. The conversation surface is off by default (`conversation_enabled = false`) because the base-thesis form is observed, not conversed with. When conversation is off, `/` redirects to `/diagnostics/`.

The shipped `[nexus].access` is `"open"`: no token or sign-in is required, and viewing and control are both open. Setting it to `"token"` restores the operator token and session sign-in. `KAINE_NEXUS_ACCESS` overrides the config value. `[nexus].read_only` and `KAINE_NEXUS_READ_ONLY` refuse every request except `GET`, `HEAD`, and `OPTIONS` with `403`. Host and Origin checks always apply. `KAINE_NEXUS_EXTRA_HOSTS` adds tailnet names.

---

## State encryption

Persisted cognitive state — Eidolon self-model, fork/merge snapshots, sidecar JSONL, and Phantasia checkpoints — is encrypted at rest with AES-256-GCM from the `cryptography` package. GCM provides authenticated encryption: any tampering with ciphertext, nonce, or tag fails decryption. A fresh 96-bit nonce from `os.urandom` is used for every encryption call. The on-disk framing (`KAINE_MAGIC || nonce(12) || ciphertext+tag`, base64-encoded) lets a disabled reader pass plaintext through unchanged.

The shipped config sets `[security.state_encryption].enabled = true`. The key is read from `KAINE_STATE_KEY` or from the Linux kernel keyring as a fallback. If neither provides a key, boot is refused. The key is never hardcoded, logged, or persisted. `cryptography` is imported lazily, so a disabled deployment never touches it. Key rotation and cross-host transfer are covered in [Security and privacy](../13-security-and-privacy.md).

---

## Cognitive cycle and bus client

The cycle is implemented in Python asyncio. All modules are coroutine-based, and the bus client (`kaine.bus.client.AsyncBus`) uses `redis.asyncio`. asyncio lets many concurrent modules share one event loop; CPU-heavy work such as embedding, video encoding, and the CfC forward pass blocks only its own coroutine for at most one tick.

The target conscious rate is adaptive. At rest it runs near `experiential_rate_hz = 3.333`, and when `[cycle.access_rate].enabled` is `true` it scales up toward 10 Hz with arousal and salience.

At boot the cycle entrypoint calls `apply_hardware_config()`, which sets PyTorch's CPU thread pool cap from `[hardware].cpu_threads` when it is set.

---

## Hardware allocation

The shipped config targets a dual-GPU reference host: a modern multi-core CPU with 32 GB+ RAM, a primary GPU with ~12 GB+ VRAM (`cuda:0` for the LLM and training), and a secondary GPU with ~8 GB VRAM (`cuda:1` for vision and TTS). Single-GPU and CPU-only hosts are supported through graceful fallback.

| Component | Default device | Config key or override |
|---|---|---|
| Lingua model server | `cuda:0` | `CUDA_VISIBLE_DEVICES` in the model-server launch config |
| Hypnos voice-alignment training | `cuda:0` (time-shares with inference) | `[hypnos.voice_alignment].training_device` |
| Topos InternVideo-Next encoder | `cuda:1` | `[topos].device` |
| Sentence-transformers embedder | `cpu` | `[embedding].device` (NumPy backend ignores this) |
| Audition emotion2vec+ | `cpu` | `[audition].emotion_device` |
| Chronos CfC network | `cpu` | pinned in `kaine/modules/chronos/network.py` |
| Chatterbox TTS | `cuda:1` | `CUDA_VISIBLE_DEVICES` in the Chatterbox systemd unit |
| Speaches STT | `cpu` | `CUDA_VISIBLE_DEVICES` in the Speaches systemd unit |

Device selection is not just a fallback chain. `resolve_device()` in `kaine/hardware.py` is bounded by `[hardware].allowed_devices`, `KAINE_FORCE_DEVICE`, and the compose device map variables (`KAINE_ORGAN_GPU`, `KAINE_VISION_GPU`, `KAINE_TRAINER_GPU`). `[hardware].cpu_threads` caps the torch thread pool, not device selection. On a single-GPU host `cuda:1` falls back to `cuda:0` with a warning, then to `cpu`; nothing crashes, but performance may drop.

---

## Licensing

KAINE is released under the Cognitive Architecture License (CAL) v0.2, a custom entity-welfare copyleft license. It combines an AGPL copyleft backbone with ethical-use covenants, cognitive-integrity provisions, copyfarleft commercial restrictions, and Guardianship governance. The text is in `LICENSE.md` and tracked in `kaineone/cognitive-architecture-license`.

Dependencies are screened for license compatibility; notes are in [Appendix C](../appendix-c-licences.md). The main rejected candidate is parselmouth (Praat Python bindings, GPL-3.0), which is incompatible with the CAL and was replaced by librosa. Redis 7.2's BSD-3-Clause license is compatible with local embedded use. The Kokoro TTS archive is a current exception: it bundles espeak-ng data under GPL-3.0-or-later, which is incompatible with the CAL and must be treated accordingly in any distributed build.
