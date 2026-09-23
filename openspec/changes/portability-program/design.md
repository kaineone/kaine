## Context

This design records the 2026-09-22 portability audit and the model research behind the phase plan in `proposal.md`. Each later phase opens its own change and design; this file is the shared reference.

## Per-module audit (code as of 2026-09-22)

Every heavy dependency is imported lazily: importing all of `kaine.*` with torch, transformers, ncps, sentence-transformers, pynvml, qdrant-client, funasr, jax and snntorch blocked succeeds, and the core imports in about 57 MB. The blockers are what the modules need once they run.

| Module | Heaviest dependency today | Lightest backend today | Needed for the torch-free core |
| --- | --- | --- | --- |
| Soma | torch + ncps CfC forward model | none | NumPy CfC (closed form), verified against the torch path |
| Chronos | torch + ncps CfC | none | NumPy CfC |
| Mnemos | sentence-transformers MiniLM; Qdrant optional | sqlite-vec store, torch embedder | shared ONNX or model2vec embedder |
| Empatheia | its own MiniLM | none | shared embedder |
| Hypnos | a third MiniLM; DPO training needs a GPU | runs without the embedder | shared embedder; training stays off on edge tiers |
| Nous | pymdp on JAX | `FakeEngine` (does not reason) | NumPy active inference |
| Phantasia | JAX DreamerV3 | dev-only EMA stub (does not learn) | small NumPy world model |
| Topos | torch + transformers (DINOv2 / InternVideo-Next) | DINOv2-small on torch | ONNX MobileNetV4 / DINOv2-S |
| Audition | STT over HTTP; emotion2vec+ in-process on torch | STT offloaded, emotion off | sherpa-onnx STT; prosody-based affect |
| Vox | Chatterbox over HTTP | none local | sherpa-onnx Kokoro / Piper / KittenTTS |
| Lingua | 4–9B model over an OpenAI-compatible server | llama.cpp in-process GGUF | already portable |
| Thymos, Eidolon, Praxis, Perception, Syneidesis | pure Python | — | — |

Timing: `EntityClock.period = 1/(hz × scale)`; a cycle overrun starts the next tick at once and records slip, while subjective time keeps tracking wall time × scale. Only a lowered `time_scale` preserves the dynamics on slow hardware, and it is set by hand today.

## Model ladder (research, 2026-09-22)

One model family across tiers keeps the persona consistent: Qwen3.5 (Apache-2.0), with community abliterated builds at 2B, 4B, 9B, 27B, 35B-A3B and 397B-A17B (none found at 0.8B; KAINE can abliterate its own). Abliterated models lose quality faster at Q3/Q2, so the lowest tiers must be tested before relying on them.

| Tier (example host) | Language | Speech in | Speech out | Embeddings | Vision |
| --- | --- | --- | --- | --- | --- |
| Pi Zero 2 W (512 MB) | SmolLM2-360M Q3 (~3 tok/s measured) | Moonshine Tiny / streaming zipformer | Flite / KittenTTS | model2vec potion | MobileNetV4-small |
| Phone, 4 GB | Qwen3.5-2B abliterated Q4 | streaming zipformer / Parakeet-TDT-0.6B-v3 int8 | Kokoro / Piper | potion-32M / MiniLM | DINOv2-S |
| Pi 5, 8 GB | Qwen3.5-2B→4B abliterated | Moonshine v2 Small | Kokoro | bge-small | DINOv2-S / SigLIP2-B |
| Jetson Orin, 8 GB | Qwen3.5-4B abliterated (current) | Parakeet-TDT-0.6B-v3 | Kokoro → Chatterbox Turbo | bge-m3 | DINOv2-B |
| Workstation, 24 GB | Qwen3.5-9B→27B abliterated | Whisper large-v3-turbo | Chatterbox | Qwen3-Embedding-4B | InternVideo-Next |
| Multi-GPU | Qwen3.5-397B-A17B abliterated | Whisper large-v3 | expressive TTS | Qwen3-Embedding-8B | InternVideo-Next large |

A smartwatch-class device (for example a Pebble) is a microphone and display for a phone, not a host: Pebble's own dictation runs Parakeet-TDT-0.6B-v3 in the phone app, not on the watch.

sherpa-onnx (Apache-2.0) covers speech in, speech out, voice activity detection and speaker ID on Android, Raspberry Pi and RISC-V without torch, so it is the natural backbone for the small tiers.

Memory stores are bound to the embedding model that wrote them: moving an entity up or down the ladder, or to a new caretaker on different hardware, requires re-embedding its memories. That belongs in the transfer design (`entity-key-custody`) as well as here.

Measured edge reference: a full voice turn on a Pi Zero 2 W (whisper.cpp tiny.en, SmolLM2-360M Q3, Flite) takes 37–46 s at 267 MB peak, loading one model at a time.

## Licence notes

Compatible with a copyleft release: Qwen3.5, SmolLM2/3, Gemma 4 (Apache-2.0), Phi-4-mini, BitNet b1.58 (MIT), Parakeet-TDT v2/v3 (CC-BY-4.0), Whisper, Moonshine (English only), Kokoro, KittenTTS, Chatterbox, Silero VAD, model2vec, MiniLM, bge, DINOv2, SigLIP2, MobileNetV4.

Avoid or review before use:
- **NVIDIA Open Model License** (streaming Parakeet, Nemotron speech). Rights terminate on bypassing safety guardrails, which conflicts with abliteration.
- **Revenue-capped:** Cactus ($2M) and LFM ($10M).
- **Use-restricted or custom:** DINOv3, Gemma 3 and EmbeddingGemma, Supertonic (OpenRAIL-M), TEN VAD, and Moonshine for non-English languages (non-commercial).
- **InternVideo-Next:** licence not confirmed. It is the current default vision encoder, so confirm it.
- **Piper engine:** now GPL-3.0; check compatibility with CAL.

Sources are listed in the research notes of the 2026-09-22 session and must be re-verified when each phase's change is designed.
