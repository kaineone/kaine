# Deployment tiers — the portability ladder

KAINE is *the architecture*, not the hardware. The mind is the loop, and the
loop is mostly cheap CPU coordination around a few heavy models. The goal of the
`portability-program` change is for the same mind to inhabit hardware ranging
from a retired phone to a datacenter, **trading capability for reach rather than
changing identity**; today every tier still carries a PyTorch runtime. This
document is the honest capability matrix: what each tier can and cannot do today.

The portability cliff is the **PyTorch / transformers / sentence-transformers /
ncps runtime**. Base dependencies include `torch`, `transformers`,
`sentence-transformers`, `ncps`, `qdrant-client`, and `pynvml`, so a plain
`pip install` of KAINE fails on 32-bit ARM and on Termux (there are no torch
wheels for Android/Termux or 32-bit ARM). The `portability-program` change is
staged to remove that cliff — Phase 2 introduces a torch-free core, Phase 3
brings Termux and JAX-free reasoning, and Phase 4 adds residency and multi-node
support. The tier ladder describes the intended backend set once those phases
land; today's shipped backends are listed in the staging section.

## Tier recommendation

`scripts/probe-host` and the first-run wizard recommend a tier from a memory budget (unified: system RAM; discrete: the smaller of RAM and total VRAM across GPUs): Tier 3 for two or more GPUs with >= 16 GB, Tier 2 for one GPU with >= 16 GB, Tier 2 with module residency required for 6–16 GB (module residency is not implemented yet, so such hosts keep the base-thesis module set, serve a language model that fits such as the 4B GGUF, and keep vision/voice extras off), Tier 1 below 6 GB or without an accelerator; the wizard writes `[deployment].profile` only when the operator confirms, and `KAINE_PROFILE` / `--profile` still take precedence.

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
which *backend* each already-selected module uses on the chosen hardware, and
disables faculties the host cannot bear.

## Capability matrix

| Faculty | Tier 0 — edge/sensor | Tier 1 — CPU agent | Tier 2 — workstation | Tier 3 — datacenter |
|---|---|---|---|---|
| **Host (program target / runs today)** | target ~512 MB SBC / retired phone; today no 512 MB host runs the Tier 0 module set (torch and the embedders exceed the memory); the original Pi Zero (ARMv6) and Termux cannot install the torch stack at all | target 4–8 GB SBC / 8 GB phone; today 64-bit Linux SBCs with 4–8 GB (for example a Pi 4/5 or a Jetson) can run it on CPU, slowly; phones cannot until Phase 3 | 1–2 GPU workstation | multi-GPU server |
| **Language (Lingua)** | sub-1B GGUF, slow (llama.cpp) | 1–2B GGUF, chat pace (llama.cpp) | Gemma/Qwen on GPU (Ollama) | larger LLM, long context |
| **Vision (Topos)** | ✗ absent | periodic, CPU (ONNX/dinov2.cpp — target) | streaming DINOv2/InternVideo (torch) | higher-rate |
| **Speech-in (Audition STT)** | optional whisper.cpp-tiny batch (target) | whisper.cpp / faster-whisper (target) | faster-whisper > realtime | > realtime |
| **Vocal emotion** | ✗ absent | ✗ absent | emotion2vec+ | emotion2vec+ |
| **Speech-out (Vox TTS)** | ✗ absent | Piper (plain — target) | Chatterbox (expressive) | Chatterbox |
| **Memory embeddings** | sentence-transformers MiniLM (torch, CPU) — ONNX/static is the Phase-2 target | sentence-transformers MiniLM (torch, CPU) — ONNX/static is the Phase-2 target | sentence-transformers (torch) | sentence-transformers |
| **Vector store (Mnemos)** | sqlite-vec (in-process) | sqlite-vec (in-process) | Qdrant (server) | Qdrant |
| **Torch runtime required** | yes (today) — removed in portability-program Phase 2 | yes (today) — removed in portability-program Phase 2 | yes | yes |
| **Disabled by profile** | topos, audition, vox, empatheia, phantasia | vox, vocal emotion | (none) | (none) |

Explicit **absences** (stated so a tier is never oversold):

- **No expressive TTS and no vocal emotion below Tier 2.** emotion2vec+ (funasr)
  has no clean edge port; it is a Tier-2-only faculty. Below it, vocal emotion is
  explicitly disabled (`[audition].emotion_model_id = ""`), not silently faked.
- **Vision is periodic, not streaming, at Tier 1** — seconds per frame on the SBC
  CPU. The ONNX/dinov2.cpp vision backend is not yet built; today Topos on CPU
  still runs through the torch path where enabled.
- **A ≥2B language model does not fit a ~512 MB Tier-0 host.** Tier 0 is a
  symbolic-reasoning + episodic-memory + perception node, not a conversational
  host.
- **Torch is required at every tier today.** Even Tier 0 and Tier 1 need the
  torch stack because Soma and Chronos run torch+ncps CfC networks and Mnemos,
  Empatheia, and Hypnos build sentence-transformers MiniLM embedders.

## Per-tier install notes

The runtime venv stays lean: a backend's third-party dependency is imported only
when that backend is selected, so you install a tier's extras and no others.

- **Tier 0 — edge / sensor node.** `llama-cpp-python` (in-process GGUF Lingua)
  and `sqlite-vec` (in-process Mnemos vector store). The profile disables topos,
  audition, vox, empatheia, and phantasia. **Torch is still required today**:
  Mnemos builds a sentence-transformers MiniLM embedder, and Soma/Chronos run
  torch+ncps CfC networks. A sub-1B GGUF model file. Measured: a full voice turn
  on a Raspberry Pi Zero 2 W (512 MB) with whisper.cpp tiny.en + SmolLM2-360M +
  Flite takes 37–46 s when loading one model at a time. The whisper.cpp-tiny
  batch STT, Piper TTS, ONNX vision, and ONNX/static embeddings backends are
  staged seams — when selected they degrade to their declared fallback.
- **Tier 1 — embodied CPU agent.** As Tier 0, but keeps Topos on CPU and enables
  audition. Vox and vocal emotion remain disabled. The intended ONNX MiniLM /
  ONNX vision / whisper.cpp / Piper backends are staged seams; today the
  torch-backed sentence-transformers embedder and llama.cpp Lingua run here.
- **Tier 2 — workstation (default).** Ollama for Lingua, Qdrant for Mnemos,
  sentence-transformers (torch), faster-whisper + emotion2vec+ (torch/funasr),
  Chatterbox. This is what `pip install -e .` + the first-run wizard provision
  today.
- **Tier 3 — datacenter / multi-GPU.** The Tier-2 stack; scale up model ids,
  context lengths, and per-module GPU placement in `config/kaine.operator.toml`.
  Multi-instance fleets and cross-host module splits are the companion
  `distributed-substrate` change, not this one.

## Staging status

Shipped today: the backend-selection framework, Tier-2-preserving defaults, the
`llama.cpp`/GGUF Lingua backend, the `sqlite-vec` Mnemos backend, the four tier
profiles, and the host probe. The core also ships torch-backed backends used by
every tier: torch+ncps CfC networks for Soma and Chronos, and
sentence-transformers MiniLM embedders for Mnemos, Empatheia, and Hypnos.

Not yet built: whisper.cpp STT, Piper/Kokoro local TTS, ONNX vision, ONNX/static
embeddings, NumPy CfC, and JAX-free Nous/Phantasia. Those backends are the focus
of the `portability-program` change (Phase 2 removes the torch requirement from
the core, Phase 3 brings Termux and JAX-free reasoning, Phase 4 adds residency,
arm64 images, and multi-node). Each backend is lazy-imported: a host that
selects an unshipped backend degrades to its declared fallback with a surfaced
reason rather than crashing boot.
