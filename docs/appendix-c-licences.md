# Licences

The licence appendix lists the licenses of KAINE's required dependencies, optional install extras, container services, models, and vendored third-party code. Use it when auditing what ships with a deployment, choosing `pip` extras, or checking compatibility with KAINE's own Cognitive Architecture License (CAL) v0.2. For the rationale behind each technology choice, see [Technology choices](02-architecture/tech-choices.md).

## Compatibility principle

CAL is a copyleft license with entity-welfare covenants. Its copyleft clause requires modifications to KAINE to be shared back under CAL. A dependency license is compatible if it does not impose obligations that conflict with those covenants or with CAL's copyleft structure.

Permissive licenses such as MIT, BSD, Apache-2.0, ISC and PSF impose no incompatible copyleft or use restrictions, so they are compatible.

Strong copyleft GPL-family licenses (GPL-2.0, GPL-3.0) are **incompatible** as runtime Python dependencies: they would require the combined work to be distributed under GPL, overriding CAL's covenants and copyleft. LGPL-3.0 is acceptable when the package is used unmodified as a separately installed, replaceable library, as with `easydict` under the `internvideo` extra. Vendored browser modules such as `viz.js` are loaded as separate front-end modules and are recorded separately in [`THIRD_PARTY_LICENSES.md`](../THIRD_PARTY_LICENSES.md).

KAINE pins Redis 7.2, which is BSD-3-Clause. The Redis RSALv2/SSPL licensing started with Redis 7.4, so it does not apply to the version shipped by KAINE. Operators who swap in Redis 7.4 or later must evaluate that license themselves.

## Core Python dependencies

These packages are installed with every KAINE install ([`pyproject.toml`](../pyproject.toml)):

| Package | License | CAL compatible |
|---|---|---|
| Python 3.11+ | PSF-2.0 | Yes |
| `redis` | MIT | Yes |
| `pydantic` | MIT | Yes |
| `psutil` | BSD-3-Clause | Yes |
| `numpy` | BSD-3-Clause | Yes |
| `httpx` | BSD-3-Clause | Yes |
| `cryptography` | Apache-2.0 | Yes |

## Optional-extra dependencies

These packages are only installed when you select an extra, for example `pip install kaine[audio,vision]`. Some packages appear under more than one extra.

| Extra | Package | License | CAL compatible |
|---|---|---|---|
| `audio` | `sounddevice` | MIT | Yes |
| `audio` | `webrtcvad` | Apache-2.0 | Yes |
| `audio` | `funasr` | Apache-2.0 per upstream; unverified | Yes |
| `audio` | `librosa` | ISC | Yes |
| `audio` | `av` (PyAV) | BSD; wheels bundle LGPL FFmpeg | Yes |
| `vision` | `opencv-python-headless` | Apache-2.0 | Yes |
| `vision` | `transformers` | Apache-2.0 | Yes |
| `vision` | `Pillow` | MIT-CMU | Yes |
| `core` | `torch` | BSD-3-Clause | Yes |
| `core` | `ncps` | Apache-2.0 | Yes |
| `memory` | `qdrant-client` | Apache-2.0 | Yes |
| `memory` | `sentence-transformers` | Apache-2.0 | Yes |
| `memory-edge` | `sqlite-vec` | see upstream | — |
| `nexus` | `fastapi` | MIT | Yes |
| `nexus` | `uvicorn` | BSD-3-Clause | Yes |
| `nexus` | `jinja2` | BSD-3-Clause | Yes |
| `nvidia` | `pynvml` | MIT per upstream; unverified | Yes |
| `reasoning` | `inferactively-pymdp` | MIT | Yes |
| `reasoning` | `jax[cpu]` | Apache-2.0 | Yes |
| `training` | `unsloth` | Apache-2.0 per upstream; unverified | Yes |
| `training` | `trl` | Apache-2.0 | Yes |
| `training` | `peft` | Apache-2.0 | Yes |
| `training` | `datasets` | Apache-2.0 | Yes |
| `worldmodel` | `jax[cpu]` | Apache-2.0 | Yes |
| `worldmodel` | `chex` | Apache-2.0 | Yes |
| `worldmodel` | `einops` | MIT | Yes |
| `internvideo` | `timm` | Apache-2.0 | Yes |
| `internvideo` | `easydict` | LGPL-3.0 | Yes: used unmodified as a separately installed, replaceable package |
| `internvideo` | `einops` | MIT | Yes |
| `internvideo-flash` | `flash-attn` | see upstream | — |
| `oscillator` | `snntorch` | MIT | Yes |
| `oscillator` | `scipy` | BSD-3-Clause | Yes |
| `speech-edge` | `sherpa-onnx` | Apache-2.0 | Yes |

The optional substrate plugin in `plugins/kaine-cl1` (a separate distribution, not installed with KAINE) uses Cortical Labs' `cl-sdk`, which is licensed CC BY-NC 4.0 (non-commercial use only). KAINE neither bundles nor installs it; operators who enable that plugin install it themselves. See [Plugins and CL1](19-plugins-and-cl1.md).

## Test dependencies

| Package | License | CAL compatible |
|---|---|---|
| `pytest` | MIT | Yes |
| `pytest-asyncio` | Apache-2.0 | Yes |
| `fakeredis` | BSD-3-Clause | Yes |
| `import-linter` | see upstream | — |

## Runtime services

| Service | License | CAL compatible | Notes |
|---|---|---|---|
| Redis 7.2 | BSD-3-Clause | Yes | `redis:7.2-alpine` image in [`compose/kaine.yml`](../compose/kaine.yml) |
| Qdrant | Apache-2.0 | Yes | |
| llama.cpp server (`ghcr.io/ggml-org/llama.cpp:server-*`) | MIT | Yes | Shipped LLM inference host ([`compose/kaine.yml`](../compose/kaine.yml)) |
| Speaches | MIT | Yes | STT host service; serves faster-Whisper |

## Trainer image

The trainer container ([`Dockerfile`](../Dockerfile)) installs its own copy of `torch` and `torchvision`, the training extras listed above, and the llama.cpp conversion tooling.

| Component | License | Notes |
|---|---|---|
| `torch` (trainer image copy) | BSD-3-Clause | |
| `torchvision` | BSD-3-Clause | |
| llama.cpp `convert_lora_to_gguf.py` / `convert_hf_to_gguf.py` | MIT | |
| `conversion` package | MIT | |
| `gguf-py` | MIT | |
| `sentencepiece` | see upstream | |
| `protobuf` | see upstream | |

## Model and weight licenses

| Model / weights | License | Notes |
|---|---|---|
| Published KAINE organ — GGUF (`kaineone/Qwen3.5-4B-abliterated-GGUF`) and safetensors (`kaineone/Qwen3.5-4B-abliterated`) | Apache-2.0 | KAINE's abliteration of Qwen3.5-4B; GGUF served via the local model server, safetensors is the Stage-2 trainer base |
| InternVideo-Next base (`revliter/internvideo_next_base_p14_res224_f16`, OpenGVLab) | MIT | Frozen temporally-native visual encoder (Topos, shipped default). Modeling code vendored in [`external/internvideo_next/`](../external/internvideo_next/); weights fetched at setup. Off Meta. |
| Dasheng base (`mispeech/dasheng-base`, Xiaomi) | Apache-2.0 | Frozen self-supervised acoustic encoder (Audition, selectable). Modeling code vendored in [`external/dasheng/`](../external/dasheng/); weights fetched at setup. |
| WavJEPA base (`labhamlet/wavjepa-base`) | MIT (per the HF model tag; no LICENSE file in the repo) | Frozen self-supervised acoustic encoder (Audition, selectable; student path only). Modeling code vendored in [`external/wavjepa/`](../external/wavjepa/) with three safety changes; weights fetched at setup. |
| `facebook/dinov2-small` | Apache-2.0 | Frozen ViT-S/14 visual encoder (Topos, selectable non-default fallback) |
| emotion2vec+ (`emotion2vec/emotion2vec_plus_base`) | Apache-2.0 | Loaded via funasr from HuggingFace hub |
| `all-MiniLM-L6-v2` | Apache-2.0 | Sentence-transformers memory embedder (Mnemos) |
| Whisper / faster-Whisper (`Systran/faster-distil-whisper-medium.en`) | MIT | Served by Speaches STT host service |
| sherpa-onnx Moonshine base/tiny | see upstream | Fetched at setup ([`kaine/setup/speech_models.py`](../kaine/setup/speech_models.py)) |
| Kokoro v0.19 | see upstream | Fetched at setup ([`kaine/setup/speech_models.py`](../kaine/setup/speech_models.py)) |
| Chatterbox TTS | per upstream / not bundled | Operator-provided host service; not distributed with KAINE. Confirm with your Chatterbox installation before deployment. |

## Vendored third-party code

| Component | Location | License | Notes |
|---|---|---|---|
| DreamerV3 RSSM | [`external/dreamerv3/`](../external/dreamerv3/) | MIT | Clean-room re-implementation of the world-model core only; full upstream license text in `external/dreamerv3/UPSTREAM` |
| OpenNARS-for-Applications | [`external/archive/`](../external/archive/) | MIT | Archived; not imported at runtime |
| InternVideo-Next modeling code | [`external/internvideo_next/`](../external/internvideo_next/) | MIT | Verbatim vendor |
| jlens | [`external/jlens/`](../external/jlens/) | Apache-2.0 | |
| Nexus front-end assets | [`kaine/nexus/static/`](../kaine/nexus/static/) | mixed | JavaScript libraries in `vendor/`; fonts in `fonts/`. Includes three.js, uPlot, and `viz.js` (GPL-3.0-or-later). See [`THIRD_PARTY_LICENSES.md`](../THIRD_PARTY_LICENSES.md). |

The project `NOTICE` file currently lists only DreamerV3 and OpenNARS as third-party components; it does not yet list InternVideo-Next or jlens. Check [`THIRD_PARTY_LICENSES.md`](../THIRD_PARTY_LICENSES.md) for the full vendored set.

## Deliberate GPL rejection

`parselmouth` (Praat Python bindings) was a candidate for prosody extraction in Audition, but it is GPL-3.0. A GPL-3.0 dependency would require the combined work to be distributed under GPL-3.0, overriding CAL's entity-welfare covenants and copyleft structure, so KAINE does not use it.

The replacement is `librosa` (ISC), which provides equivalent prosody extraction with no copyleft conflict. The reason for choosing `librosa` is in [Technology choices](02-architecture/tech-choices.md) under the Audition section.

KAINE does not depend on any GPL-licensed Python package. One vendored front-end asset, [`viz.js`](../kaine/nexus/static/vendor/viz.js), is GPL-3.0-or-later; it is recorded in [`THIRD_PARTY_LICENSES.md`](../THIRD_PARTY_LICENSES.md).
