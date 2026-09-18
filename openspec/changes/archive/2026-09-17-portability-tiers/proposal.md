## Why

KAINE today assumes one machine: a dual-GPU Linux workstation. The thesis,
though, is that KAINE is *the architecture*, not the hardware — "the mind is the
loop," and the loop is mostly cheap CPU coordination around a few heavy models.
If that is true, the same mind should be able to inhabit hardware ranging from a
retired phone to a datacenter, trading capability for reach rather than changing
identity. We want KAINE to run, at some level of capability, on a ~512 MB-class
single-board computer (SBC), a retired Android phone under Termux, a 4–8 GB-class
SBC, the current workstation, and a multi-GPU server.

The architecture is already most of the way there and we should say why:

- **Modules are config-toggled.** `build_registry` (`kaine/boot.py:515`) only
  constructs modules whose `[modules].<name>` flag is true. A subset is already
  expressible with zero code change.
- **Devices resolve leniently.** `kaine/hardware.py:resolve_device` already
  falls back `cuda:1 → cuda:0 → cpu` with a warning instead of crashing, and
  `tune_cpu_threads` caps the CPU pool. A single-GPU or CPU-only host already
  boots.
- **External model endpoints are config keys**, not hardcoded
  (`[lingua].chat_url`, `[mnemos.qdrant]`, `[audio_in].speaches_url`,
  `[audio_out].chatterbox_url`).

The real portability cliff is **not** the GPU — it is the **PyTorch/transformers/
funasr runtime**. Research into the field's edge-deployment practice (2026) is
unambiguous: anything in the GGML/ONNX family (llama.cpp, whisper.cpp,
dinov2.cpp, ONNX-Runtime) ports down to a ~512 MB-class SBC; anything that requires the
torch graph realistically needs a 4–8 GB-class SBC minimum. So the lever that
unlocks the low-end is a **per-component runtime backend**, plus **named tier
profiles** that select a coherent module subset + backends for a host class, and
a **host probe** that recommends a tier. None of this changes the cognitive
architecture; it changes which *implementation* of each organ is loaded.

This is design-first and additive. The current workstation behavior is "Tier 2"
and must remain the untouched default.

## What Changes

- **Runtime-backend selection per heavy component.** Each component that today
  hard-binds to a single runtime gains a `[<module>].backend` (or
  `[<module>].engine`) config key selecting an interchangeable implementation
  behind the module's existing internal client interface:

  | Component | Default (Tier 2) | Edge backend | Project |
  |---|---|---|---|
  | Lingua LLM | Ollama (`chat_url`) | llama.cpp / GGUF | llama.cpp |
  | Audio-In STT | Speaches/faster-whisper | whisper.cpp (GGML) | whisper.cpp |
  | Audio-Out TTS | Chatterbox (expressive) | Piper (VITS→ONNX) | rhasspy/piper |
  | Topos vision | DINOv2 via transformers/torch | DINOv2 ONNX / dinov2.cpp | onnxruntime / dinov2.cpp |
  | Mnemos embeddings | sentence-transformers (torch) | ONNX MiniLM | onnxruntime |
  | Mnemos vector store | Qdrant (server) | sqlite-vec (in-process) | asg017/sqlite-vec |
  | Audio-In emotion | emotion2vec+ (funasr) | *(none — disabled below Tier 2)* | — |

- **Named tier profiles** shipped as overlay configs (e.g.
  `config/profiles/tier0.toml` … `tier3.toml`) that set module toggles, backend
  selections, device hints, and cycle-rate hints for a host class. A profile is
  applied as a layer over the shipped `kaine.toml`; the local working config
  still wins for operator overrides.

- **A host-capability probe** (`kaine.hardware` extension or
  `scripts/probe-host`) that reports RAM, CPU arch (armv6 / aarch64 / x86_64),
  CUDA/MPS presence, and torch importability, and **recommends** a tier. It only
  recommends; the operator chooses.

- **Graceful degradation as a contract.** A module whose configured backend
  cannot load on the current host SHALL downgrade to a lighter backend or
  disable itself with a logged, surfaced reason — never crash the boot. This
  extends the existing `resolve_device` leniency to the runtime dimension.

- **An honest capability matrix** (docs + paper) stating what each tier can and
  cannot do — e.g. no expressive TTS and no vocal-emotion below Tier 2,
  periodic (not streaming) vision on Tier 1, and that a ≥2B LLM does **not** fit
  a ~512 MB-class single-board computer (SBC) (it is a symbolic-reasoning +
  memory + sensor node, not a conversational host).

This change adds capabilities `deployment-tiers`, `runtime-backends`, and
`host-probe`. It does not modify the cognitive cycle, the workspace, or any
module's semantics — only which engine realizes a given organ.
