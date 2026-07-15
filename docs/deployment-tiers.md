# Deployment tiers — the portability ladder

KAINE is *the architecture*, not the hardware. The mind is the loop, and the
loop is mostly cheap CPU coordination around a few heavy models. So the same
mind can inhabit hardware ranging from a retired phone to a datacenter, **trading
capability for reach rather than changing identity**. This document is the honest
capability matrix: what each tier can and cannot do.

The portability cliff is **not** the GPU — it is the **PyTorch / transformers /
funasr runtime**. Anything in the GGML/ONNX family (llama.cpp, whisper.cpp,
dinov2.cpp, sqlite-vec, ONNX Runtime) ports down to a ~512 MB-class single-board
computer (SBC); anything that needs the torch graph realistically needs a
4–8 GB-class SBC minimum. The tier ladder is built around that single fact.

Selecting a tier is an **operator action**. Run the host probe for a
recommendation, then choose the profile deliberately — nothing auto-applies:

```
.venv/bin/python scripts/probe-host          # recommends a tier; never applies one
KAINE_PROFILE=tier1 python -m kaine.cycle     # or: python -m kaine.cycle --profile tier1
```

A profile is a TOML overlay (`config/profiles/tierN.toml`) layered **between**
the shipped defaults and your local `config/kaine.operator.toml` — your local
config still wins. Profiles are inert and voice-free: they never enable a module
or embed a private voice (those stay local operator actions). Which faculties are
*active* is a separate, orthogonal choice from the tier: the default is the
**base-thesis form** (Soma, Chronos, Topos, Audition, Thymos, Lingua — see the
`thesis_test` profile), and a tier profile never changes that — it only bounds
which *backend* each already-selected module uses on the chosen hardware.

## Capability matrix

| Faculty | Tier 0 — edge/sensor | Tier 1 — CPU agent | Tier 2 — workstation | Tier 3 — datacenter |
|---|---|---|---|---|
| **Host** | ~512 MB SBC / retired phone | 4–8 GB SBC / 8 GB phone | 1–2 GPU workstation | multi-GPU server |
| **Language (Lingua)** | sub-1B GGUF, slow (llama.cpp) | 1–2B GGUF, chat pace (llama.cpp) | Gemma/Qwen on GPU (Ollama) | larger LLM, long context |
| **Vision (Topos)** | ✗ absent | periodic, CPU (ONNX/dinov2.cpp) | streaming DINOv2/InternVideo (torch) | higher-rate |
| **Speech-in (Audition STT)** | optional whisper.cpp-tiny batch | whisper.cpp / faster-whisper | faster-whisper > realtime | > realtime |
| **Vocal emotion** | ✗ absent | ✗ absent | emotion2vec+ | emotion2vec+ |
| **Speech-out (Vox TTS)** | ✗ absent | Piper (plain) | Chatterbox (expressive) | Chatterbox |
| **Memory embeddings** | — | ONNX MiniLM | sentence-transformers (torch) | sentence-transformers |
| **Vector store (Mnemos)** | sqlite-vec (in-process) | sqlite-vec (in-process) | Qdrant (server) | Qdrant |
| **Torch runtime required** | no | optional | yes | yes |

Explicit **absences** (stated so a tier is never oversold):

- **No expressive TTS and no vocal emotion below Tier 2.** emotion2vec+ (funasr)
  has no clean edge port; it is a Tier-2-only faculty. Below it, vocal emotion is
  explicitly disabled (`[audition].emotion_model_id = ""`), not silently faked.
- **Vision is periodic, not streaming, at Tier 1** — seconds per frame on the SBC
  CPU.
- **A ≥2B language model does not fit a ~512 MB Tier-0 host.** Tier 0 is a
  symbolic-reasoning + episodic-memory + perception node, not a conversational
  host.

## Per-tier install notes

The runtime venv stays lean: a backend's third-party dependency is imported only
when that backend is selected, so you install a tier's extras and no others.

- **Tier 0 — edge / sensor node.** `llama-cpp-python` (in-process GGUF) and
  `sqlite-vec` (in-process vector store). No torch, no Qdrant, no funasr. A
  sub-1B GGUF model file on disk. Optional: `whisper.cpp` (tiny) for manual/batch
  STT.
- **Tier 1 — embodied CPU agent.** As Tier 0, plus `onnxruntime` for MiniLM
  embeddings and ONNX/dinov2.cpp periodic vision, plus `piper-tts` for plain TTS,
  plus a STT engine (`whisper.cpp` or the `kaine[audio]` faster-whisper path on
  CPU). A 1–2B GGUF model file.
- **Tier 2 — workstation (default).** The full stack: an OpenAI-compatible model
  server (Ollama / llama-server / Unsloth Studio), Qdrant, `sentence-transformers`,
  `torch`, `kaine[audio]` (faster-whisper + emotion2vec+/funasr), Chatterbox.
  This is what `pip install -e .` + the first-run wizard provision today.
- **Tier 3 — datacenter / multi-GPU.** The Tier-2 stack; scale up model ids,
  context lengths, and per-module GPU placement in `config/kaine.operator.toml`.
  Multi-instance fleets and cross-host module splits are the companion
  `distributed-substrate` change, not this one.

## Staging status

Landed: the backend-selection framework, Tier-2-preserving defaults, the
`llama.cpp`/GGUF Lingua backend, the `sqlite-vec` Mnemos backend, the four tier
profiles, and the host probe. The remaining edge backends (whisper.cpp STT, Piper
TTS, ONNX/dinov2.cpp vision, ONNX MiniLM embeddings) are staged seams — the tier
ladder is designed for them and this doc lists them, but they land in follow-ups.
Each is lazy-imported: a host that selects an unshipped backend degrades to its
declared fallback with a surfaced reason rather than crashing the boot.
