## Separation of concerns

- Generator (`generate_maternal_voice.py`): render, resample, lowpass, manifest `generator` block.
- Plan emitter (`render_maternal_voice_sam.py`): `build_render_plan()` validates adapter boundary before generator runs: `output_sample_rate==8000`, `output_format=="FLAC"`, `subtype=="PCM_16"`, `spectral_ceiling_hz==300`.
- Tests import `apply_prosody_muffling` and `SPECTRAL_CEILING_HZ` directly; these must be exposed/aliased so plan and generator cannot drift.

## Content

Syllable/nonlexical prosody content (no intelligible words) for the unintelligible stimulus. 300 Hz low-pass (`SPECTRAL_CEILING_HZ`/`lowpass_hz`/`lowpass_cutoff_hz` all 300).

## Manifest contract

Sam `generator` block is single source of truth. Fields kept: `tool`, `renderer`, `sam_model_repo`, `sam_model_source`, `sam_model_path`, `sam_speaker`, `sam_checkpoint`, `sam_sample_rate`, `base_seed`, `spectral_ceiling_hz`, `lowpass_hz`, `lowpass_cutoff_hz`, `trim_top_db`, `target_rms_dbfs`, `peak_ceiling_dbfs`, `watermark`. Added: `generation_params` (`"model defaults (not exposed)"` or named constants), `resampler` (`"soxr_hq"`). `reference_voice.attribution` and empty `files` remain correct for Sam; no reference WAV produced/consumed.

## Honesty rules

- Sam never attempts CMU-ARCTIC download; `--reference-dir` is Chatterbox-only.
- Local-path source asserts `spk_id["sam"]==3000` and `tts_model_type=="custom_voice"`; otherwise raise, no silent fallthrough.
- Generation params either explicit marker or named constants; nothing implied.

## Non-goals

- No generator/audio change in this package (task-doc + design only).
- Default remains `chatterbox`; flipping default is separate.
- No manifest migration; `format` stays `1`.