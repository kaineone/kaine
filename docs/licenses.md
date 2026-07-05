# Dependency License Manifest

This document records the license of every dependency and runtime service used
by KAINE, and asserts compatibility with the Cognitive Architecture License
(CAL) v0.2. For the full rationale behind each technology choice see
[docs/tech-choices.md](tech-choices.md).

---

## Compatibility principle

CAL is a custom entity-welfare copyleft license. Its copyleft clause (Article
2.2) requires that modifications to the Software be shared back under CAL. For
a dependency license to be compatible it must not impose obligations
inconsistent with CAL's entity-welfare covenants or its copyleft structure.

Permissive licenses (MIT, BSD-*, Apache-2.0, ISC, PSF) are compatible: they
impose no copyleft and no prohibited-use restrictions.

GPL-family licenses are **incompatible**: GPL-3.0 requires the combined work to
be distributed under GPL-3.0, which would override CAL's entity-welfare
covenants. See the [deliberate GPL rejection note](#deliberate-gpl-rejection)
below.

Redis RSALv2/SSPL is acceptable for KAINE's local embedded deployment (the
SSPL SaaS clause does not apply to private local use).

---

## Core Python dependencies

| Package | License | CAL compatible |
|---|---|---|
| Python 3.11+ | PSF-2.0 | Yes |
| `redis` | MIT | Yes |
| `pydantic` | MIT | Yes |
| `psutil` | BSD-3-Clause | Yes |
| `pynvml` | MIT | Yes |
| `numpy` | BSD-3-Clause | Yes |
| `torch` | BSD-3-Clause | Yes |
| `ncps` | Apache-2.0 | Yes |
| `transformers` | Apache-2.0 | Yes |
| `Pillow` | MIT-CMU | Yes |
| `qdrant-client` | Apache-2.0 | Yes |
| `sentence-transformers` | Apache-2.0 | Yes |
| `httpx` | BSD-3-Clause | Yes |
| `fastapi` | MIT | Yes |
| `uvicorn` | BSD-3-Clause | Yes |
| `jinja2` | BSD-3-Clause | Yes |
| `cryptography` | Apache-2.0 | Yes |

---

## Optional-extra dependencies

| Package | Extra | License | CAL compatible |
|---|---|---|---|
| `sounddevice` | `audio` | MIT | Yes |
| `webrtcvad` | `audio` | Apache-2.0 | Yes |
| `funasr` | `audio` | Apache-2.0 | Yes |
| `librosa` | `audio` | ISC | Yes |
| `opencv-python-headless` | `vision` | Apache-2.0 | Yes |
| `inferactively-pymdp` | `reasoning` | MIT | Yes |
| `jax[cpu]` | `reasoning`, `worldmodel` | Apache-2.0 | Yes |
| `unsloth` | `training` | Apache-2.0 | Yes |
| `trl` | `training` | Apache-2.0 | Yes |
| `peft` | `training` | Apache-2.0 | Yes |
| `datasets` | `training` | Apache-2.0 | Yes |
| `chex` | `worldmodel` | Apache-2.0 | Yes |
| `einops` | `worldmodel` | MIT | Yes |
| `snntorch` | `oscillator` | MIT | Yes |
| `scipy` | `oscillator` | BSD-3-Clause | Yes |

---

## Test dependencies

| Package | License | CAL compatible |
|---|---|---|
| `pytest` | MIT | Yes (dev only) |
| `pytest-asyncio` | Apache-2.0 | Yes (dev only) |
| `fakeredis` | BSD-3-Clause | Yes (dev only) |

---

## Runtime services (containerized / host)

| Service | License | CAL compatible | Notes |
|---|---|---|---|
| Redis 7.2 | RSALv2/SSPL | Yes (local use) | SSPL SaaS clause does not apply to private local deployment |
| Qdrant | Apache-2.0 | Yes | |
| Unsloth Studio / unsloth-core | Apache-2.0 | Yes | LLM inference host service (OpenAI-compatible model server); serves via llama.cpp (MIT) / vLLM (Apache-2.0) under the hood — both permissive |

---

## Model and weight licenses

| Model / weights | License | Notes |
|---|---|---|
| Published KAINE organ — GGUF (`kaineone/Qwen3.5-4B-abliterated-GGUF`) and safetensors (`kaineone/Qwen3.5-4B-abliterated`) | Apache-2.0 | KAINE's own abliteration of Qwen3.5-4B; GGUF served via the local model server, safetensors is the Stage-2 trainer base; license follows the Apache-2.0 base |
| `facebook/dinov2-small` | Apache-2.0 | Frozen ViT-S/14 visual encoder (Topos) |
| emotion2vec+ (`iic/emotion2vec_plus_base`) | Apache-2.0 | Loaded via funasr from HuggingFace hub |
| `all-MiniLM-L6-v2` | Apache-2.0 | Sentence-transformers memory embedder (Mnemos) |
| Whisper / faster-Whisper (`Systran/faster-distil-whisper-medium.en`) | MIT | Served by Speaches STT host service |
| Chatterbox TTS | per upstream / not bundled | Operator-provided host service; not distributed with KAINE. License is per upstream; confirm with your Chatterbox installation before deployment. |

---

## Deliberate GPL rejection

`parselmouth` (Praat Python bindings) was the initial candidate for prosody
extraction in Audition. It was rejected **solely on license grounds**: `parselmouth`
is GPL-3.0. Introducing a GPL-3.0 dependency would require the combined work
to be distributed under GPL-3.0, overriding CAL's entity-welfare covenants and
copyleft structure — an incompatible constraint.

The replacement is `librosa` (ISC), which provides equivalent prosody extraction
with no copyleft incompatibility. This decision is documented in
[docs/tech-choices.md](tech-choices.md) under the Audition section.

---

## Vendored third-party code

| Component | Location | License | Notes |
|---|---|---|---|
| DreamerV3 RSSM | `external/dreamerv3/` | MIT | Clean-room re-implementation of the world-model core only; full license text in `external/dreamerv3/UPSTREAM` |
| OpenNARS-for-Applications | `external/archive/` | MIT | Archived; not imported at runtime |
