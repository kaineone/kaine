# Maternal voice Sam OpenSpec package note (2026-11-16)

Task-doc only. No source, tests, manifest, audio, or OpenSpec files are changed by this document. It summarizes what would need to become a real OpenSpec change package in order to make `--renderer sam` a first-class, provenance-honest backend, without performing the generator edit.

## 1. Purpose

`tools/maintainer/generate_maternal_voice.py` already parses `--renderer sam` and contains a `render_sam_take` implementation, with its own lowpass, manifest block, and source selection. `tools/maintainer/render_maternal_voice_sam.py` is the claimed contract owner, but only emits a dry-run plan and carries no validation boundary. The gap between those two surfaces is the subject of this note: the OpenSpec package that would close it.

## 2. Candidate change package

- Proposed change name: `maternal-voice-sam-renderer`
- Target repository: `openspec/changes/maternal-voice-sam-renderer/`
- Composition (none created yet): `proposal.md`, `design.md`, `tasks.md`, and `specs/`
- Relation to existing changes: complementary to, not replacing, `sam-voice-training` (which covers dataset, cloning, fine-tune, catalogue) and the archived `20-2026-10-19-developmental-maternal-voice` change (which covers the Chatterbox rollout). This package covers the rendering backend and its contract.

## 3. Why

The Chatterbox path is the legacy licensed authoring path and default. Sam is the intended alternate backend with a distinct spectral profile (300 Hz ceiling) and distinct provenance (Qwen3-TTS Sam checkpoint, no Perth watermark). For the two to be interchangeable by flag, the Sam path must be (a) drift-free against its contract owner, (b) honest about generation parameters it does not expose, and (c) validated at the checkpoint boundary rather than failing silently into a fallback source.

## 4. What Changes (proposed)

- Align Sam resampling with the Chatterbox path by using `res_type="soxr_hq"` in the `librosa.resample` call, so determinism comparisons are valid across backends.
- Gate `--reference-dir` as Chatterbox-only in help text and in any code path it touches; Sam must never attempt CMU-ARCTIC download.
- Assert the selected v2 checkpoint `config.json` contains `spk_id["sam"] == 3000` and `tts_model_type == "custom_voice"` when the source is a local path, raising a clear error instead of silently falling through.
- Record Sam generation provenance honestly: either record `"generation_params": "model defaults (not exposed)"` explicitly, or introduce named constants before any non-default is used.
- Expose / alias `apply_prosody_muffling` and `SPECTRAL_CEILING_HZ` for test import, so the plan emitter and generator cannot drift.
- Make `render_maternal_voice_sam.py` `build_render_plan()` validate the adapter boundary before the generator runs: `output_sample_rate == 8000`, `output_format == "FLAC"`, `subtype == "PCM_16"`, `spectral_ceiling_hz == 300`.
- Add test coverage for items 1 through 6 in a new PR; do not weaken `test_maternal_voice_sam_conversion.py` or `test_maternal_sam_backend_smoke.py`.

## 5. Control changes (manifest / provenance)

Sam `generator` block (already emitted by the generator's Sam branch) must remain the single source of truth and gain the following control fields:

- Keep existing fields: `tool`, `renderer`, `sam_model_repo`, `sam_model_source`, `sam_model_path`, `sam_speaker`, `sam_checkpoint`, `sam_sample_rate`, `base_seed`, `spectral_ceiling_hz`, `lowpass_hz`, `lowpass_cutoff_hz`, `trim_top_db`, `target_rms_dbfs`, `peak_ceiling_dbfs`, `watermark`.
- Add `generation_params`: either the explicit `"model defaults (not exposed)"` marker or named constants objects, so provenance stays honest.
- Add `resampler`: `"soxr_hq"` once item 1 lands, matching Chatterbox.
- `reference_voice.attribution` and empty `files` remain correct for Sam; no reference WAV is produced or consumed.
- All three spellings of the 300 Hz ceiling (`spectral_ceiling_hz`, `lowpass_hz`, `lowpass_cutoff_hz`) must agree with `render_maternal_voice_sam.py` constants.

## 6. Proposed task list (not yet executed)

- [ ] 0.1 Confirm change name and place; do not alter any generator file in this note.
- [ ] 1.1 Edit `tools/maintainer/generate_maternal_voice.py` resampling call to add `res_type="soxr_hq"` on the Sam path.
- [ ] 1.2 Update `--reference-dir` help/parser to mark it Chatterbox-only / deprecated under `--renderer sam`.
- [ ] 1.3 Add checkpoint `config.json` assertion in `load_sam_model` for local-path source.
- [ ] 1.4 Record declared Sam generation parameters in the Sam `generator` block.
- [ ] 1.5 Expose / alias `apply_prosody_muffling` and `SPECTRAL_CEILING_HZ` for test import.
- [ ] 1.6 Add adapter-boundary validation in `tools/maintainer/render_maternal_voice_sam.py` `build_render_plan()`.
- [ ] 2.1 Add tests for items 1.1 through 1.6.
- [ ] 2.2 Run the existing Maternal Sam tests unchanged and keep them green.
- [ ] 3.1 Run `--verify` before and after any future render on the Sam output directory.
- [ ] 3.2 `openspec validate maternal-voice-sam-renderer --strict` passes once the change is created.
- [ ] 4.1 Documentation update: note in `docs/09-modules/audition.md` or the operator docs that `--renderer sam` requires the v2 checkpoint and applies no implicit watermark, once the backend is promoted beyond dry-run.

## 7. Verification gates for the future change

- `tests/test_maternal_sam_backend_smoke.py` remains green and unchanged.
- `tests/test_maternal_voice_sam_conversion.py` remains green and unchanged.
- New tests exercise the six items above without weakening those.
- Full runtime test set after the edit.
- `--verify` run against the Sam output directory both before and after a render.
- Manifest field agreement between generator and plan emitter (ceiling 300, rate 8000, FLAC, PCM_16).

## 8. Non-goals

- No generator change is made by this note.
- No audio is rendered or regenerated.
- `--renderer` default remains `chatterbox`; flipping the default is separate and gated on a passing full smoke run.
- No manifest migration is proposed; manifest `format` stays `1`, with additive provenance fields only.
- No runtime playback, module, or config (`config/kaine.toml`) change is implied.

## 9. Cross-references

- `docs/records/maternal-sam-implementation-probe-2026-11-16.md`
- `docs/records/maternal-voice-sam-render-plan-2026-11-16.md`
- `docs/records/maternal-sam-conversion-phase2-2026-11-16.md`
- `docs/records/maternal-voice-sam-conversion-plan-2026-11-16.md`
- `docs/records/maternal-voice-sam-smoke-2026-11-16.md`
- `tools/maintainer/generate_maternal_voice.py`
- `tools/maintainer/render_maternal_voice_sam.py`
- `kaine/modules/audition/maternal_voice.py`
- `openspec/changes/sam-voice-training/`
