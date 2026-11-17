## Why

Maternal voice rendering currently defaults to the Chatterbox path (licensed authoring). The Sam backend (`--renderer sam`) is the intended alternate that yields an unintelligible-prosody stimulus: a 300 Hz low-passed, nonlexical (syllable) signal used for maternal/prosody studies. Sam uses the Qwen3-TTS Sam checkpoint with no Perth watermark, a distinct spectral profile, and a distinct manifest contract. Today Sam is only partially wired: `generate_maternal_voice.py` parses `--renderer sam` and implements `render_sam_take`, while `render_maternal_voice_sam.py` is a dry-run plan emitter with no validation boundary. The two drift.

This change package makes the Sam backend a first-class, contract-honest renderer for unintelligible prosody. It does not alter the default (Chatterbox remains default), renders no audio, and changes no runtime/module/config. Task-doc and tests only until generator edits land.

## What Changes

- Sam backend generator data conversion, tasks 1.1-1.6:
  - resample with `res_type="soxr_hq"` for cross-backend determinism;
  - gate `--reference-dir` as Chatterbox-only;
  - assert v2 checkpoint `config.json` has `spk_id["sam"]==3000` and `tts_model_type=="custom_voice"` for local paths;
  - record Sam generation provenance honestly (`"model defaults (not exposed)"` or named constants);
  - expose/alias `apply_prosody_muffling` and `SPECTRAL_CEILING_HZ` for test import;
  - add adapter-boundary validation in `render_maternal_voice_sam.py.build_render_plan()`.
- Syllable/nonlexical prosody content for the unintelligible stimulus.
- 300 Hz low-pass and manifest contract (all three ceiling spellings agree; rate 8000, FLAC, PCM_16).
- Validation/housekeeping (`--verify`, manifest field agreement, smoke tests unchanged).
- Tests for items 1.1-1.6.
- Docs updates.

## Capabilities

### New Capabilities

- `maternal-voice-unintelligible-prosody`: Sam renderer as contract-honest alternate backend for unintelligible (prosody-only) maternal voice, with validated checkpoint boundary and manifest provenance.

### Modified Capabilities

None. Additive only: manifest `format` stays `1` with additive provenance fields.

## Impact

- Affected: `tools/maintainer/generate_maternal_voice.py`, `tools/maintainer/render_maternal_voice_sam.py`, docs.
- No runtime, module, config, audio, or manifest migration changes.
- Complementary to `sam-voice-training` and the archived `20-2026-10-19-developmental-maternal-voice` change.