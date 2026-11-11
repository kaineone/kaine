# Design

## Context

Three files carry the default model identity for the Qwen3-TTS backend: the client class (`qwen3_tts.py`), the boot factory (`vocal.py`), and the shipped config (`kaine.toml`). All three currently point at `Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice` with an empty speaker string. The provisioning system (`provision.py`) adds HuggingFace aux models for other backends but has no entry for Qwen3-TTS; the model downloads on first use via `from_pretrained`, which is opaque and not consent-gated.

See proposal.md for motivation.

## Goals / Non-Goals

**Goals:**

- Point the three default-carrying files at `kaineone/Qwen3-TTS-Sam-0.6B` with speaker `"sam"`.
- Add the Sam model to the provisioning plan so the setup wizard downloads it with operator consent before first run.
- Report the correct speaker in prosody metadata, consistent with the other backends.

**Non-Goals:**

- Supporting multiple switchable voices or voice retraining (deferred per proposal).
- Changing the sherpa-onnx or chatterbox provisioning paths.
- Modifying the operator override file (`kaine.operator.toml`); it inherits the new defaults.

## Decisions

### 1. Default constants in the client class

Change `model_id` and `speaker` field defaults on the `Qwen3TTS` dataclass. The factory and config derive from these, so one authoritative source stays in the client.

Alternative: move defaults to config only and require the factory to always pass them. Rejected because the client should be usable standalone with sensible defaults, and the existing pattern for all three backends keeps defaults on the client class.

### 2. Provisioning via AuxModel, not speech_models.py

`speech_models.py` handles sherpa-onnx tar archives with SHA-256 pinning and safe extraction. HuggingFace models use `huggingface_hub.snapshot_download`, which has its own integrity checks (ETag + SHA-256 per blob). Adding a parallel HF-download path to `speech_models.py` would duplicate logic already in `provision.py`'s aux-model pipeline.

The change adds a conditional `AuxModel` entry in `aux_models()` when `backend == "qwen3_tts"`, mirroring the existing Chatterbox block at lines 160-163. The wizard's consent gating and progress display apply automatically.

Alternative: pin the HF model by commit SHA in `speech_manifest.py`. Rejected because the aux-model path already handles HF repos, and a manifest entry adds complexity without benefit (the HF hub tracks revisions natively).

### 3. Config comments, not config values

`kaine.toml` ships with the Qwen3-TTS settings commented out (the shipped default backend is `chatterbox`). The change updates the commented-out model ID and speaker string so operators who uncomment them get the right defaults. No uncommented values change.

## Risks / Trade-offs

**2.4 GB download added to setup** — The Sam model is 2.4 GB. Operators selecting the `qwen3_tts` backend will see this in the wizard's consent list. Mitigation: the wizard already shows name, size, and license for each model before downloading. No silent downloads.

**HuggingFace availability** — If HuggingFace is unreachable, the download fails and the wizard reports it. This is the same behavior as the existing organ and vision model downloads. No new failure mode.

**No offline fallback** — Without the download, the `qwen3_tts` backend will fail to load the model at boot. This is the existing behavior for all HF-hosted models and is reported clearly. The operator can switch to `sherpa_onnx` (bundled) as a fallback.
