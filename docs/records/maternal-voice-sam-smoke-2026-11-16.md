# Maternal voice, Sam render-plan smoke result

Date: 2026-11-16

Status: smoke/validation record only. No source code, tests, manifest, audio, or checked-in state changed by this record beyond this document.

## Commands run

```bash
cd /var/home/erik/Projects/kaineone/kaine
python tools/maintainer/render_maternal_voice_sam.py --dry-run --json
```

Result: exit status `0`; stdout parsed as valid JSON.

```bash
cd /var/home/erik/Projects/kaineone/kaine
.venv/bin/pytest -q \
  tests/test_maternal_voice.py \
  tests/test_maternal_voice_build_context.py \
  tests/test_maternal_voice_threads.py \
  tests/test_stimulus_source_maternal_voice.py
```

Result: `1278 passed in 16.02s`, zero failures.

## Render-plan validation

- JSON parse: valid.
- Mode: `dry-run` (`dry_run: true`).
- Synthesis flags: `synthesizes_audio`, `renders_audio`, `audio_synthesized` all `false`.
- Sam model:
  - name: `Qwen3-TTS-Sam`
  - model: `Qwen3-TTS-Sam-0.6B`
  - path: `/run/media/erik/2TBm2Store/kaine/qwen3-tts-training/sam-model-v2/checkpoint-epoch-1`
  - checkpoint: `checkpoint-epoch-1`
  - speaker: `sam`
  - base model: `Qwen/Qwen3-TTS-12Hz-0.6B-Base`
  - license: `Apache-2.0`
- Prosody/contract fields:
  - spectral ceiling: `300`
  - output sample rate: `8000`
  - output format: `FLAC`
  - PCM/bit depth: `PCM_16` / `16`
  - manifest format: `1`
- Inventory:
  - texts path: `kaine/modules/audition/maternal_voice_data/texts.toml`
  - output directory: `kaine/modules/audition/maternal_voice_data`
  - item count: `20`
  - kinds: `phrase`, `passage`
  - all 20 item records include `index`, `id`, `kind`, `takes`, `text_length`, and `output_file_pattern` (`{id}.t{take}.flac`).
- Checkpoint present on disk: directory and `config.json` exist; `config.json` declares `tts_model_type: custom_voice` with `spk_id` containing `sam`.

## Subset testing

The `render_maternal_voice_sam.py` CLI does not support a `--only` option. Only `--dry-run`, `--json`, `--texts`, `--out`, and `--sam-model-path` are supported. Therefore a single-item render-plan subset could not be exercised through this helper; limitation recorded. The existing generator `tools/maintainer/generate_maternal_voice.py` documents `--only`, but that generator remains Chatterbox-based and was not run here to avoid changing offline artifacts.

## Conclusion

The Sam render-plan helper emits valid JSON with the required model, prosody, manifest, and item fields and does not synthesize audio in dry-run mode. Existing maternal-voice tests remain green (`1278 passed`). No source edits were made.
