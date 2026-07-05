# Design — portability tiers

## The cliff is the runtime, not the accelerator

KAINE's per-cycle cost is dominated by a small number of heavy models; the
twelve modules themselves are cheap coordination. Soma, Chronos (CfC, ~3.5K
params), Nous (the ONA C binary), Thymos, Eidolon, Syneidesis, and the faithful
renderer are "negligible resource" and already CPU-pinned. The cost — and the
portability problem — lives in six components: the Lingua LLM, Topos vision,
Audio-In STT, Audio-In emotion, Audio-Out TTS, and Mnemos embeddings + vector
store.

For each, the field already ships a runtime that is dramatically lighter than
the torch/transformers/funasr default, and the dividing line for the whole stack
is whether a component runs on the **GGML/ONNX** runtimes (C/C++, NEON-SIMD, no
torch) or the **PyTorch** runtime. The GGML family runs on a ~512 MB-class SBC;
torch realistically needs a 4–8 GB-class SBC. This is the single fact the tier ladder is built
around. (See research notes; representative figures below are CPU-only.)

| Component | Heavy runtime | Edge runtime | Indicative edge perf |
|---|---|---|---|
| LLM | Ollama/torch | llama.cpp + GGUF Q4 | phone ~4–6 tok/s (2B Q4); 4–8 GB-class SBC ~12–18 tok/s (1.1B) |
| STT | faster-whisper | whisper.cpp tiny | tiny = 75 MB file / ~273 MB RAM; near-realtime on a 4–8 GB-class SBC |
| TTS | Chatterbox | Piper | 60–150 MB voices, comfortable on a 4–8 GB-class SBC |
| Vision | DINOv2/transformers | dinov2.cpp / ONNX | seconds/image on the SBC CPU — periodic, not streaming |
| Embeddings | sentence-transformers | ONNX MiniLM | efficient on SBC CPU via ONNX-Runtime |
| Vector store | Qdrant server | sqlite-vec | near-zero idle footprint, single-user |
| Vocal emotion | emotion2vec+/funasr | **(no clean edge port)** | drop below Tier 2 |

## Where the abstraction goes

Every heavy module already talks to its model through an internal client class —
`lingua/client.py`, `audio_in/stt_client.py`, `audio_out/client.py`,
`topos/encoder.py`, `mnemos/storage.py`. The backend selector lives **behind
those interfaces**: a `[<module>].backend` key picks a concrete client; the
module body, the bus contracts, and the published event shapes are unchanged.
This keeps the blast radius inside each module and preserves the structural
invariants (e.g. Lingua still emits the same `lingua.speech` events; Mnemos
still stores the same CLS collections, whether the index is Qdrant or
sqlite-vec).

Backends are **lazy-imported**, exactly as the `[training]` extras already are:
a host without `llama-cpp-python` installed but with Ollama running picks the
Ollama backend; the GGUF path imports nothing torch- or llama.cpp-related until
selected. This keeps Tier 2 installs from pulling edge dependencies and vice
versa.

## Tier profiles as config overlays

A tier profile is **not** new code — it is a TOML overlay applied over the
shipped `config/kaine.toml`, then over the operator's local working config. Load
order: shipped defaults → selected profile (`KAINE_PROFILE=tier1` or
`--profile`) → local `kaine.toml` operator overrides → secrets. This reuses the
existing layered-load idea (`_load_kaine_config` + secrets merge) and keeps the
local-config-wins rule that protects module toggles and the private voice.

The four shipped profiles:

- **Tier 0 — edge / sensor node** (~512 MB-class SBC or retired low-RAM phone).
  Modules: soma, chronos, nous, mnemos (sqlite-vec), eidolon, thymos, a sub-1B
  GGUF Lingua (slow), optional whisper.cpp-tiny batch STT. No Topos, no emotion,
  no Chatterbox. Honest role: symbolic reasoning + episodic memory + perception
  satellite, optionally feeding a higher tier over the bus.
- **Tier 1 — embodied CPU agent** (4–8 GB-class SBC, or retired 8 GB flagship
  smartphone under a userland like Termux). Adds whisper.cpp/faster-whisper STT,
  Piper TTS, ONNX MiniLM embeddings, ONNX/dinov2.cpp **periodic** vision,
  mic/cam via device APIs. 1–2B GGUF LLM at chat pace. No expressive TTS, no
  vocal emotion, no streaming vision, short contexts.
- **Tier 2 — workstation** (current default, unchanged). Full real-time
  multimodal: Gemma E2B on GPU via Ollama, DINOv2 torch, emotion2vec+,
  faster-whisper >realtime, Chatterbox, Qdrant, sentence-transformers.
- **Tier 3 — datacenter / multi-GPU.** Larger LLMs, longer contexts, multiple
  concurrent instances, higher-rate vision, redundancy. Same architecture, more
  headroom. (Multi-instance fleets and cross-host module splits are the subject
  of the companion `distributed-substrate` change, not this one.)

## Host probe

`scripts/probe-host` (and an importable `kaine.hardware.recommend_tier`) reports:
total RAM, CPU architecture (armv6 → Tier 0 LLM-only-toy ceiling; aarch64;
x86_64), CUDA/MPS availability, and whether `torch` imports successfully. It maps
those to a recommended tier and prints the capability matrix row for that tier.
It **recommends**; the operator selects the profile. The probe never auto-applies
a profile — consistent with operator-supervised boot.

## Graceful degradation

Today `resolve_device` degrades the *device* dimension. This change adds the
*runtime* dimension: each module's backend factory attempts its configured
backend, and on `ImportError`/load failure logs a structured warning, surfaces
it on the Nexus diagnostics health surface, and either (a) falls back to a
declared lighter backend or (b) disables the module (registry simply does not
register it) — never raising into the boot path. A module disabled this way is
reported, not silent: silent truncation of capability reads as "it works" when
it doesn't.

## Non-goals

- No change to module semantics, bus contracts, the cycle, or the workspace.
- No new cloud/runtime network dependency (per the all-local invariant); edge
  backends are themselves local.
- Cross-host distribution and batch offload are out of scope here — see
  `distributed-substrate`.
- Implementing every backend at once. Tasks below stage the backends; the
  framework + Tier 2-preserving defaults + one proven edge backend (llama.cpp)
  land first.

## References

- llama.cpp / whisper.cpp (ggml-org), Piper (rhasspy), dinov2.cpp, sqlite-vec
  (asg017), ONNX Runtime — the edge runtimes named above.
- Gemma 3n MatFormer / Per-Layer-Embedding caching (the "E2B" effective-2B
  mode) — why the chosen organ already has an edge story.
- Existing KAINE mechanisms reused: `kaine/boot.py:build_registry` (toggles),
  `kaine/hardware.py` (`resolve_device`, `tune_cpu_threads`),
  `_load_kaine_config` layered load, the `[training]` lazy-import pattern.
