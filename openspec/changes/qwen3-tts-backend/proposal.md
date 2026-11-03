# Qwen3-TTS vocal backend

## Problem

The vocal module has two backends — Chatterbox (HTTP, Llama backbone, Meta
dependency) and Kokoro (sherpa-onnx, CPU, emotionally flat). The entity needs an
Apache 2.0, Meta-free voice engine with affect-driven prosody that runs locally
on GPU. Qwen3-TTS fills this: 0.6B CustomVoice on the RTX 3070, built-in
speakers, natural-language `instruct` for emotion/style, no service process.

## Solution

Add `backend = "qwen3_tts"` to the vocal module's `BackendRegistry`. A new
`Qwen3TTS` class in `kaine/modules/vocal/qwen3_tts.py` loads the model
in-process via the `qwen-tts` package and exposes the same `TTSClient` protocol
the module already consumes.

### Model

`Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice` (~4-6 GB VRAM, bfloat16).
Tokenizer: `Qwen/Qwen3-TTS-Tokenizer-12Hz`.

### Affect -> instruct mapping

A new function `affect_to_instruct(state: DimensionalState) -> str` maps the
entity's current valence/arousal/dominance into a natural-language instruct
string (e.g. "Speak with warm enthusiasm" when valence + arousal are high). The
vocal module passes the instruct through a new optional `instruct` field on
`TTSRequest`.

### Applied prosody

The Qwen3 backend reports `APPLIED_PROSODY = ("instruct", "speed_factor",
"language")`. Speed factor maps to `generate_custom_voice` kwargs if supported,
otherwise a post-process resample.

### Config keys (under `[vocal]`)

```toml
backend = "qwen3_tts"
qwen3_model_id = "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
qwen3_tokenizer_id = "Qwen/Qwen3-TTS-Tokenizer-12Hz"
qwen3_device = "cuda:1"
qwen3_dtype = "bfloat16"
qwen3_speaker = ""       # auto-pick from model.get_supported_speakers()
```

### Dependency

New pip extra `speech-qwen3`: `qwen-tts>=0.1`. torch and
torchaudio are already present.

### Unload/reload

Like SherpaKokoroTTS: reversible `unload()` frees VRAM; `ensure_loaded()`
restores on demand. InflightGate prevents unload during inference.

### Files changed

| File | Change |
|------|--------|
| `kaine/modules/vocal/qwen3_tts.py` | New: `Qwen3TTS` class |
| `kaine/modules/vocal/client.py` | Add `instruct: Optional[str] = None` to `TTSRequest` |
| `kaine/modules/vocal/mapping.py` | Add `affect_to_instruct()` |
| `kaine/modules/vocal/module.py` | Pass instruct when backend is qwen3_tts |
| `kaine/boot/factories/vocal.py` | Register `qwen3_tts` backend |
| `kaine/extras.py` | Add `speech-qwen3` extra |
| `kaine/faithful/episodic_own_content.py` | Add `"qwen3_tts"` to `VOCAL_BACKENDS` |
| `kaine/dashboard/health/config.py` | Add health probe for qwen3_tts |
| `config/kaine.toml` | Document new config keys |
| `tests/test_qwen3_tts.py` | Unit tests (mocked model) |

## Risks

- The 0.6B variant has weaker instruction compliance than 1.7B; affect mapping
  may need tuning after real inference tests.
- First load downloads ~1.5 GB of weights; subsequent loads use cache.
- flash-attn is optional; without it, inference is slower but functional.

## Decision

CTO decided Qwen3-TTS as main voice engine (2026-11-03).
