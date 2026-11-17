## 0. Setup

- [ ] 0.1 Confirm change name/place; no generator edits in this package.

## 1. Sam backend generator data conversion

- [ ] 1.1 Resample Sam path with `res_type="soxr_hq"` in `librosa.resample`.
- [ ] 1.2 Gate `--reference-dir` as Chatterbox-only (help text and code paths).
- [ ] 1.3 Assert checkpoint `config.json`: `spk_id["sam"]==3000`, `tts_model_type=="custom_voice"` for local-path source.
- [ ] 1.4 Record Sam generation provenance (`generation_params`: `"model defaults (not exposed)"` or named constants).
- [ ] 1.5 Expose/alias `apply_prosody_muffling` and `SPECTRAL_CEILING_HZ` for test import.
- [ ] 1.6 Add adapter-boundary validation in `render_maternal_voice_sam.build_render_plan()` (rate 8000, FLAC, PCM_16, ceiling 300).

## 2. Content

- [ ] 2.1 Define syllable/nonlexical prosody content for unintelligible stimulus.

## 3. 300 Hz low-pass and manifest contract

- [ ] 3.1 Ensure `SPECTRAL_CEILING_HZ`/`lowpass_hz`/`lowpass_cutoff_hz` all agree at 300.
- [ ] 3.2 Emit `generation_params` and `resampler="soxr_hq"` in Sam `generator` block.
- [ ] 3.3 Keep `reference_voice.attribution` and empty `files` correct for Sam.

## 4. Validation / housekeeping

- [ ] 4.1 Run `--verify` before/after any future Sam render.
- [ ] 4.2 Validate manifest field agreement (ceiling 300, rate 8000, FLAC, PCM_16).

## 5. Tests

- [ ] 5.1 Add tests for items 1.1-1.6.
- [ ] 5.2 Keep `test_maternal_sam_backend_smoke.py` and `test_maternal_voice_sam_conversion.py` green and unchanged.

## 6. Docs

- [ ] 6.1 Note in operator/audition docs that `--renderer sam` requires v2 checkpoint and applies no implicit watermark.