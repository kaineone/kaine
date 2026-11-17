# Maternal voice Sam seed utility status (2026-11-16)

Date: 2026-11-16

Status: docs only. No source code, tests, manifest, or audio changed by this record.

## Purpose

This record corrects an earlier report that stated `render_maternal_voice_sam_seed.py`
did not exist. That statement was inaccurate: the utility is present in the
repository, has been compiled, and now has passing offline tests after the
`tests/test_render_maternal_voice_sam_seed.py` coverage was added.

## Utility location and identity

- Canonical module under test: `tools/maintainer/render_maternal_voice_sam_seed.py`
  (`REPO_ROOT` resolves as `parents[2]`, i.e. repository root).
- Mirrored copy: `tools/render_maternal_voice_sam_seed.py`
  (`REPO_ROOT` resolves as `parents[1]`).
- Untracked offline test: `tests/test_render_maternal_voice_sam_seed.py`
  (imports the `tools/maintainer/` copy via `importlib`).

Module docstring: low-level helper for the maternal-voice (Sam) render seed. It
reads a maternal manifest, validates its spectral-ceiling metadata, and renders a
*deterministic seed command* describing the fixed render invocation. It does
**not** synthesize audio and does **not** import or load any TTS model (no
Qwen).

## Contract constants

- `SPECTRAL_CEILING_HZ == CEILING_HZ == EXPECTED_SPECTRAL_CEILING_HZ == SPECTRAL_CONE_CEILING_HZ == 300`
- Default manifest: `kaine/modules/audition/maternal_voice_data/manifest.json`
- Default texts: `kaine/modules/audition/maternal_voice_data/texts.toml`
- Default spectral ceiling passed through the CLI `--ceiling` flag: `300.0`
- Base seed default (manifest fallback): `20261018`

## Public API (stable names)

- Manifest read: `read_manifest` (aliases `read_maternal_manifest`,
  `load_manifest`).
- Ceiling validation: `validate_spectral_ceiling` (aliases
  `check_spectral_ceiling`, `validate_spectral_cone_ceiling`,
  `validate_ceiling`, `check_ceiling`).
- Builders/renderers: `build_seed_command`, `render_seed_command`
  (aliases `render_seed`, `render`, `render_seed_file`, `build_seed`,
  `create_seed`, `make_seed`, `seed_command`, `generate_seed_command`,
  `render_deterministic_seed`).
- CLI entry point: `main` (`--manifest`/`--manifest-path`, `--out`/`--output`,
  `--ceiling`).

Validation semantics: if the manifest carries no ceiling metadata, validation
succeeds (the constant contract is 300 Hz). If ceiling metadata is present it
must equal 300 Hz, otherwise `ValueError` is raised.

## Outputs

`render_seed_command(...)` writes three sibling files (default basenames under
the chosen output directory):

- `seed_command.txt` -- single-line command text.
- `seed_command.json` -- structured sidecar (`spectral_ceiling_hz`, `base_seed`,
  `command`, `renders_audio`, `synthesizes_audio`, paths, `deterministic`).
- `seed_command.sh` -- bash wrapper with `#!/usr/bin/env bash` and
  `set -euo pipefail`.

The seed command references `python tools/maintainer/generate_maternal_voice.py`
with `--renderer sam` and does not itself render audio.

## Validation performed

### Compile

```bash
cd /var/home/erik/Projects/kaineone/kaine
.venv/bin/python -m py_compile \
  tools/render_maternal_voice_sam_seed.py \
  tools/maintainer/render_maternal_voice_sam_seed.py
```

Result: exit status `0` for both copies.

### Offline tests

```bash
cd /var/home/erik/Projects/kaineone/kaine
.venv/bin/python -m pytest tests/test_render_maternal_voice_sam_seed.py -q
```

Result: `8 passed, 1 warning`. Warning is the repository's known "real KAINE
data-root guard disabled" notice; no failures.

Covered:
- bounded contract constants (`SPECTRAL_CEILING_HZ == 300`, `REPO_ROOT`).
- manifest dict acceptance and base-seed extraction.
- spectral-ceiling acceptance (300 Hz) and rejection (non-300 Hz raises).
- seed-command file write, sidecar existence/content, `renders_audio` and
  `synthesizes_audio` false.
- sample-rate contract via emitted shell sidecar shebang.
- in-memory `build_seed_command` determinism.
- rejection of bad ceiling (`440`) in manifest.

### CLI smoke

```bash
cd /var/home/erik/Projects/kaineone/kaine
rm -rf /tmp/maternal-voice-sam-seed-smoke
.venv/bin/python tools/maintainer/render_maternal_voice_sam_seed.py \
  --manifest kaine/modules/audition/maternal_voice_data/manifest.json \
  --out /tmp/maternal-voice-sam-seed-smoke
```

Result: exit status `0`; printed `/tmp/maternal-voice-sam-seed-smoke/seed_command.txt`.
All three sidecar files were produced. `seed_command.txt` emitted:

```text
python tools/maintainer/generate_maternal_voice.py --texts kaine/modules/audition/maternal_voice_data/texts.toml --out /tmp/maternal-voice-sam-seed-smoke --renderer sam
```

No audio was synthesized and no TTS model was loaded by the utility.

## Conclusion

`render_maternal_voice_sam_seed.py` exists (both the canonical maintainer copy and
the tools-root mirror), compiles cleanly, passes 8/8 offline tests, and produces
a deterministic seed command plus JSON/shell sidecars while never synthesizing
audio or loading a model. The prior report claim that it did not exist is
incorrect. No source edits were made by this record.
