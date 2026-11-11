# Proposal

## Why

The Qwen3-TTS backend defaults to `Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice`, a base model with no trained speaker. The Sam voice fine-tune (`kaineone/Qwen3-TTS-Sam-0.6B`) is validated and published on HuggingFace, but nothing in the codebase points to it, and the provisioning system doesn't download it during setup. A fresh install that selects `qwen3_tts` as the vocal backend will either fail to find a speaker or fall back to the base model's default.

## What Changes

- Change the default `model_id` in the `Qwen3TTS` client from `Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice` to `kaineone/Qwen3-TTS-Sam-0.6B`.
- Change the default `speaker` in the `Qwen3TTS` client from `""` (auto-pick) to `"sam"`.
- Update `config/kaine.toml` comments to reflect the new defaults.
- Add `kaineone/Qwen3-TTS-Sam-0.6B` to the provisioning plan when the vocal backend is `qwen3_tts`, so the setup wizard downloads it alongside the other models.
- Update the boot factory's resolved metadata to log the correct defaults.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `speech-backends`: The provisioning requirement ("Speech models are fetched only with consent and verified") must extend to Qwen3-TTS models fetched via `huggingface_hub`, not only sherpa-onnx tar archives. The Qwen3-TTS model needs to appear in the provision plan when the vocal backend is `qwen3_tts`.
- `vocal`: The shipped default voice identity changes from "no speaker, auto-pick" to the Sam speaker from the published fine-tune.

## Impact

- `kaine/modules/vocal/qwen3_tts.py`: default constructor arguments change.
- `kaine/boot/factories/vocal.py`: resolved metadata defaults change.
- `kaine/setup/provision.py`: `aux_models()` gains a Qwen3-TTS entry.
- `config/kaine.toml`: comments updated.
- No API changes, no breaking changes, no new dependencies.
