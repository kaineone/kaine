# Maternal voice Sam implementation probe (2026-11-16)

Date: 2026-11-16

Status: docs only. No source, tests, manifest, or audio changed by this document. It probes the Sam slice already present in `tools/maintainer/generate_maternal_voice.py` (the `--renderer sam` branch and `render_sam_take`), for use as the implementation reference in the next edit pass.

## Controls needed (current Sam implementation)

### Checkpoint source

- Primary source constant: `SAM_HF_MODEL_ID = "kaineone/Qwen3-TTS-Sam-0.6B"` (`tools/maintainer/generate_maternal_voice.py`, around line 77).
- Fallback source constant: `SAM_MODEL_PATH = "/run/media/erik/2TBm2Store/kaine/qwen3-tts-training/sam-model-v2/checkpoint-epoch-1"` (around line 78).
- `load_sam_model(device, sam_model_path=SAM_MODEL_PATH)` tries the HF cache first with `local_files_only=True`, then the local v2 checkpoint with no kwargs. It returns `(model, source)` where `source` is the winning source string.
- Speaker identity: `SAM_SPEAKER = "sam"` (line 79), `SAM_CHECKPOINT = "checkpoint-epoch-1"` (line 80), `SAM_SAMPLE_RATE = 24000` (line 81).
- Generation uses `model.generate_custom_voice(text=text, language="English", speaker=SAM_SPEAKER)`.

### Lowpass (prosody muffling)

- Ceiling constant: `SPECTRAL_CEILING_HZ = 300` (line 82).
- Filter: `apply_prosody_muffling(audio, sample_rate)` builds a 6th-order Butterworth lowpass (`scipy.signal.butter(..., btype="low", output="sos")`) with `cutoff = min(SPECTRAL_CEILING_HZ, nyq * 0.99)` and applies `scipy.signal.sosfiltfilt`.
- Application order in `render_sam_take`: trim (`TRIM_TOP_DB = 40.0` on the native-rate waveform), lowpass, then resample native 24 kHz to `OUTPUT_SAMPLE_RATE = 8000`, then RMS normalise to `TARGET_RMS_DBFS = -20.0`, then peak limit to `PEAK_CEILING_DBFS = -1.0`, then int16 PCM FLAC write.
- Filter is applied before resampling; the 300 Hz ceiling is declared three ways in the Sam manifest block as `spectral_ceiling_hz`, `lowpass_hz`, and `lowpass_cutoff_hz`.

### Manifest fields (Sam branch)

Top-level contract (unchanged from format 1):

- `format`, `sample_rate` (8000), `initial_unlocked`, `texts_sha256`, `generator`, `reference_voice`, `items`, `total_bytes`, `total_seconds`.

Per-item:

- `id`, `kind`, `index`, `text_sha256`, `takes`.

Per-take:

- `take`, `file`, `sha256`, `frames`, `seconds`, `seed`, `rms_dbfs`.

Sam `generator` block (lines 659-676):

- `tool`: `"tools/maintainer/generate_maternal_voice.py"`
- `renderer`: `"sam"`
- `sam_model_repo`: `SAM_HF_MODEL_ID`
- `sam_model_source`: selected source (HF cache or checkpoint path)
- `sam_model_path`: `SAM_MODEL_PATH`
- `sam_speaker`: `SAM_SPEAKER`
- `sam_checkpoint`: `SAM_CHECKPOINT`
- `sam_sample_rate`: `SAM_SAMPLE_RATE` (24000)
- `base_seed`: `BASE_SEED` (20261018)
- `spectral_ceiling_hz`, `lowpass_hz`, `lowpass_cutoff_hz`: `SPECTRAL_CEILING_HZ` (300)
- `trim_top_db`, `target_rms_dbfs`, `peak_ceiling_dbfs`
- `watermark`: `"none (Sam renderer applies no implicit watermark)"`

`reference_voice` block (Sam branch):

- `attribution`: `"Qwen3-TTS Sam"`
- `files`: `[]`
- `reference_wav_sha256`: `None`

### Rerun order (Sam branch `main`)

1. `parse_args` (defaults: texts = `<repo>/kaine/modules/audition/maternal_voice_data/texts.toml`, out = same dir, device = `cuda`, renderer = `chatterbox` unless `--renderer sam`).
2. If `--verify`: run `verify_manifest(out_dir)` and exit (no render, no model load).
3. Sam branch (selected by `--renderer sam`):
   a. Ensure `out_dir` exists.
   b. `load_texts(texts_path)` -> items, initial_unlocked, texts_sha256.
   c. If `--only`: require existing manifest; build `existing_by_id`; reject unknown ids.
   d. `load_sam_model(args.device)` -> model, source.
   e. For each item (in texts order): render all takes unless `--only` filters it (reused items are hash-verified via `reuse_existing_takes`).
   f. Sum totals; assemble manifest; write `manifest.json` (sort_keys, indent 2).
   g. Print summary.
4. Baseline/verification sequence between runs: `--verify` before and after; full runtime test set after.

### CLI flags (all)

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--texts` | Path | `<repo>/kaine/modules/audition/maternal_voice_data/texts.toml` | texts TOML input |
| `--out` | Path | `<repo>/kaine/modules/audition/maternal_voice_data` | output dir for FLAC + manifest.json |
| `--reference-dir` | Path | `~/.cache/kaine/maternal-voice-reference` | Chatterbox-only reference WAV dir; unused by Sam branch |
| `--device` | str | `cuda` | torch device for model load |
| `--renderer` | choice | `chatterbox` | `chatterbox` or `sam` (`VALID_RENDERERS`) |
| `--only` | ID (append, nargs+) | none | render only these ids; requires existing manifest |
| `--verify` | store_true | false | verify manifest + files instead of rendering |

## Next exact edit tasks (proposed, not yet applied)

1. `tools/maintainer/generate_maternal_voice.py` ~line 403-405: align Sam resampling with Chatterbox by adding `res_type="soxr_hq"` to the `librosa.resample(muffled, ... target_sr=OUTPUT_SAMPLE_RATE)` call, so determinism (S4) is comparable across backends.
2. Same file ~line 79 `--reference-dir` help/parser: mark it Chatterbox-only / deprecated when `--renderer sam`, or gate reference handling so Sam runs never attempt CMU-ARCTIC download (already true in the Sam branch, but help text still implies it).
3. Same file ~line 327-338 `load_sam_model`: add an assertion that the selected v2 checkpoint `config.json` contains `spk_id["sam"] == 3000` and `tts_model_type == "custom_voice"` when the source is a local path (adapter rule from phase-2 design), raising a clear error instead of silent fallback.
4. Same file ~line 659-676 Sam generator block: record the declared Sam generation parameters. Today Sam's `generate_custom_voice` exposes no temperature/CFG constants; either record `"generation_params": "model defaults (not exposed)"` explicitly or introduce named constants before any non-default is used, so provenance stays honest.
5. Same file new helper near `apply_prosody_muffling`: expose/alias it (and `SPECTRAL_CEILING_HZ`) for test import, matching how `tools/maintainer/render_maternal_voice_sam.py` declares the 300 Hz profile, so the plan emitter and generator cannot drift.
6. `tools/maintainer/render_maternal_voice_sam.py`: keep it the contract owner for model identity + profile; the next edit pass should make `build_render_plan()` validate that `output_sample_rate == 8000`, `output_format == "FLAC"`, `subtype == "PCM_16"`, and `spectral_ceiling_hz == 300` before the generator runs (adapter boundary #1 in the phase-2 design). Docs-only today; code is the pending task.
7. Tests: add coverage for items (1)-(6) in a new PR; do not weaken the existing `test_maternal_voice_sam_conversion.py` or `test_maternal_sam_backend_smoke.py` assertions.

## Cross-references

- `docs/records/maternal-voice-sam-conversion-plan-2026-11-16.md`
- `docs/records/maternal-sam-conversion-phase2-2026-11-16.md`
- `docs/records/maternal-voice-sam-render-plan-2026-11-16.md`
- `tools/maintainer/generate_maternal_voice.py`
- `tools/maintainer/render_maternal_voice_sam.py`
- `kaine/modules/audition/maternal_voice.py`