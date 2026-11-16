# Maternal voice, Sam rendering: activation and regeneration plan

Date: 2026-11-16

Status: render plan only. No source code, tests, manifest, or generated audio changed. This companion plan operationalises the readiness inventory and the prosody-first design document. Companion documents:

- `docs/records/maternal-voice-sam-readiness-2026-11-16.md`
- `docs/records/maternal-voice-sam-prosody-design-2026-11-16.md`

## Scope

This plan covers generating the 8 kHz maternal-voice FLAC repertoire with the Sam voice (`kaineone/Qwen3-TTS-Sam-0.6B`, speaker `"sam"`), using prosody-first content, and replacing the current Chatterbox/pre-Sam artefacts only after every gate below passes. Runtime code, manifest schema, tests, and the perception-feed contract remain unchanged except as separately proposed.

## Paths

- Texts: `/var/home/erik/Projects/kaineone/kaine/kaine/modules/audition/maternal_voice_data/texts.toml`
- Output: `/var/home/erik/Projects/kaineone/kaine/kaine/modules/audition/maternal_voice_data/`
- Current generator: `/var/home/erik/Projects/kaineone/kaine/tools/maintainer/generate_maternal_voice.py`
- Preferred model: `kaineone/Qwen3-TTS-Sam-0.6B` if an HF cache is available
- Fallback checkpoint: `/run/media/erik/2TBm2Store/kaine/qwen3-tts-training/sam-model-v2/checkpoint-epoch-1`

## Activation gates

All gates are required before rendering anything. A failure is recorded, not bypassed, and the offending slice returns to design or implementation review.

| Gate | Requirement | Pass criteria |
|---|---|---|
| A1 | Model and checkpoint selection | Exactly one Sam backend and one checkpoint path are selected and recorded in the generator provenance block. The checkpoint README and config confirm speaker `"sam"` / `spk_id["sam"] = 3000`. |
| A2 | GPU and disk resources | Free space on the model/render storage is at least 30 GiB. Local models that do not need to run are stopped. The render stays within the documented capped-run and disk guardrails. |
| A3 | Source baseline | The existing maternal-voice tests pass against the current Chatterbox rendering before any change. This establishes the regression floor. |
| A4 | Prosody content replacement | The texts source has been rewritten as prosody-first material. No take is recognizable as a sentence, transcript, or lexical passage by maintainer review. |
| A5 | Runtime contract preservation | The generator changes only offline files. Required runtime fields and sample-rate contract remain unchanged: FLAC files are 8 kHz, and `MaternalVoiceRepertoire.load(sample_rate=...)` still checks `file_rate * 2 == sample_rate` where applicable. |
| A6 | Determinism policy | `BASE_SEED` and all generation parameters are fixed, named, and included in the manifest. A repeat render can be detected by exact file SHA-256 and complete render order. |
| A7 | Provenance honesty | The generator block no longer attributes the Chatterbox Perth watermark or CMU ARCTIC reference voice. It records the actual tool chain, checkpoint path or repo, revision, seed, parameters, and an explicit watermark or no-watermark declaration. |
| A8 | Safety and welfare scope | The plan does not alter stimulus-source behavior, hearing-band behavior, unlocked-count behavior, voice level, or the perception-feed runtime. Any runtime change is a separate proposal. |

## Preflight commands

Run these before any render. They are read-only checks and record the starting state.

```bash
set -eu
REPO=/var/home/erik/Projects/kaineone/kaine
DATA=$REPO/kaine/modules/audition/maternal_voice_data
SAM_Checkpoint=/run/media/erik/2TBm2Store/kaine/qwen3-tts-training/sam-model-v2/checkpoint-epoch-1

test -d "$SAM_Checkpoint"
test -f "$SAM_Checkpoint/config.json"
grep -E '"tts_model_type"|"spk_id"' "$SAM_Checkpoint/config.json"

python -m pytest -q \
  tests/test_maternal_voice.py \
  tests/test_maternal_voice_build_context.py \
  tests/test_maternal_voice_threads.py \
  tests/test_stimulus_source_maternal_voice.py

python tools/maintainer/generate_maternal_voice.py --verify

df -h /run/media/erik/2TBm2Store
```

Gate notes:

- The model checkpoint path is selected as v2 because it carries the published model card and complete README, including the Sam speaker identity.
- `generator.py` changes should remain isolated from runtime files.
- `--verify` must pass before any rendering begins, after every render, and before tests are reported as green.

## Smoke-test sequence

This sequence must pass on a single representative item before full regeneration. Passing means every test and every verification command exits zero, with no new unexplained manifest diff.

### S0: runtime baseline

1. Capture `git status --short`.
2. Run the four existing maternal-voice test files.
3. Run `python tools/maintainer/generate_maternal_voice.py --verify`.

Pass: full test suite green, manifest verification zero, only pre-existing repository changes.

### S1: model load

1. Load Sam through the selected backend from an offline source.
2. Generate one arbitrary take for one arbitrary text.
3. Inspect the raw waveform.

Pass: model loads without network ambiguity; generated audio has nonzero RMS; output is finite.

### S2: single-item render

Once the implementation path supports Sam, render one item only. The definitive implementation command may use a renamed or parameterized generator. If future option names differ from the template below, record the actual invocation in the render notes.

```bash
set -eu
REPO=/var/home/erik/Projects/kaineone/kaine
DATA=$REPO/kaine/modules/audition/maternal_voice_data
TARGET_ID=<representative-item-id>

cd "$REPO"
python tools/maintainer/generate_maternal_voice.py \
  --texts "$DATA/texts.toml" \
  --out "$DATA" \
  --only "$TARGET_ID"

python tools/maintainer/generate_maternal_voice.py --out "$DATA" --verify
```

Pass: one item's takes are regenerated, all manifest hashes match, and every other item remains reuse-verified by byte comparison.

### S3: output contract probe

```bash
set -eu
DATA=/var/home/erik/Projects/kaineone/kaine/kaine/modules/audition/maternal_voice_data
python - <<'PY'
import soundfile as sf
from pathlib import Path
out = Path("$DATA")
files = sorted(out.glob("*.t1.flac"))
assert files, "no rendered FLAC files found"
for path in files[:3]:
    info = sf.info(path)
    assert info.samplerate == 8000, (path, info.samplerate)
    assert info.frames > 0
    assert info.subtype == "PCM_16"
    print(path.name, info.samplerate, info.frames, info.subtype)
PY
```

Pass: every probed file is 8 kHz PCM_16 with nonzero frames.

### S4: determinism replay

1. Copy the manifest and one or more rendered files to a temporary workspace.
2. Rerun the exact S2 invocation.
3. Compare SHA-256 values and use `diff -u` on the manifest.

```bash
set -eu
DATA=/var/home/erik/Projects/kaineone/kaine/kaine/modules/audition/maternal_voice_data
SCRATCH=$(mktemp -d)
cp "$DATA/manifest.json" "$SCRATCH/manifest.before.json"
python tools/maintainer/generate_maternal_voice.py --verify
diff -u "$SCRATCH/manifest.before.json" "$DATA/manifest.json"
```

Pass: no file hash or manifest field changes between identical runs.

### S5: content intelligibility

1. Run a speech recognizer over every rendered take.
2. Compare recognizer transcripts across takes of the same item.
3. Have a maintainer confirm that no lexical phrase can be recovered.

Pass: recognizer output is inconsistent or empty for all items, while pitch and intensity category information remains recoverable.

### S6: prosody retention

1. Extract fundamental-frequency contours after resampling to 8 kHz.
2. Compare contour variation with the prosody categories in the texts source.
3. Verify that prosodic categories such as statement versus question and calm versus aroused remain recoverable.

Pass: prosody contours vary in a reproducible way rather than being filtered to silence.

### S7: regression tests

```bash
set -eu
REPO=/var/home/erik/Projects/kaineone/kaine
cd "$REPO"
python -m pytest -q \
  tests/test_maternal_voice.py \
  tests/test_maternal_voice_build_context.py \
  tests/test_maternal_voice_threads.py \
  tests/test_stimulus_source_maternal_voice.py
```

Pass: all tests green, with no change to tests to accommodate generator-only work.

## Regeneration command checklist

Use this after every gate above is green. If a subset run fails, stop before full regeneration and record the failing gate.

1. Record baseline state.

   ```bash
   set -eu
   REPO=/var/home/erik/Projects/kaineone/kaine
   cd "$REPO"
   git status --short
   git rev-parse HEAD
   python tools/maintainer/generate_maternal_voice.py --verify
   ```

2. Confirm selected checkpoint and available storage.

   ```bash
   set -eu
   test -d /run/media/erik/2TBm2Store/kaine/qwen3-tts-training/sam-model-v2/checkpoint-epoch-1
   df -h /run/media/erik/2TBm2Store
   ```

3. Replace the text content with prosody-first material and review it before any render.

   - Keep the manifest's `text_sha256` reproducibility behavior.
   - Keep item ids, kinds, take counts, text structure, and TOML validity intact unless a later design change deliberately changes them.
   - Back up old lexical text data outside the generated-data run only if the operator approves that file creation.

4. Implement the Sam renderer in a separate OpenSpec change, keeping the runtime and tests untouched.

   - Prefer `kaineone/Qwen3-TTS-Sam-0.6B` when an HF cache exists.
   - Fall back to the local v2 checkpoint otherwise.
   - Pass `speaker="sam"`.
   - Preserve trim, RMS normalization, peak ceiling, and 8 kHz output.
   - Preserve fixed seeds per item and take.
   - Remove or replace Chatterbox model-download, reference-file, and watermark behavior.

5. Render one representative item.

   ```bash
   set -eu
   REPO=/var/home/erik/Projects/kaineone/kaine
   DATA=$REPO/kaine/modules/audition/maternal_voice_data
   cd "$REPO"
   printf 'Before-render verify:\n'
   python tools/maintainer/generate_maternal_voice.py --out "$DATA" --verify
   # Replace <target-id> with an item whose prosody category is explicit.
   python tools/maintainer/generate_maternal_voice.py \
     --texts "$DATA/texts.toml" \
     --out "$DATA" \
     --only <target-id>
   python tools/maintainer/generate_maternal_voice.py --out "$DATA" --verify
   python -m pytest -q \
     tests/test_maternal_voice.py \
     tests/test_maternal_voice_build_context.py \
     tests/test_maternal_voice_threads.py \
     tests/test_stimulus_source_maternal_voice.py
   ```

   Stop if S5 or S6 fails. The whole 40-take regeneration should not proceed until the smoke layout matches the intended prosody.

6. Run an intelligibility probe on the regenerated S2 item.

   - Run speech recognition with a fixed recognizer and fixed settings.
   - Inspect transcript entropy/diversity. The expected result is unstable, non-repeatable transcripts.
   - Preserve the recognizer command and parameters in the render notes.

7. Run the prosody-retention probe on the same item.

   - Extract pitch contours using constant analysis parameters.
   - Compare against the intended prosodic category.
   - Record the parameters in the render notes.

8. Regenerate all takes only when S2 through S7 pass.

   ```bash
   set -eu
   REPO=/var/home/erik/Projects/kaineone/kaine
   DATA=$REPO/kaine/modules/audition/maternal_voice_data
   cd "$REPO"
   git status --porcelain
   df -h /run/media/erik/2TBm2Store
   python tools/maintainer/generate_maternal_voice.py \
     --texts "$DATA/texts.toml" \
     --out "$DATA"
   python tools/maintainer/generate_maternal_voice.py --out "$DATA" --verify
   python -m pytest -q \
     tests/test_maternal_voice.py \
     tests/test_maternal_voice_build_context.py \
     tests/test_maternal_voice_threads.py \
     tests/test_stimulus_source_maternal_voice.py
   ```

   Full regeneration should be run under the configured capped hardware allocation and monitored for free space.

9. Rerun determinism replay on the complete repertoire and inspect the manifest generator block.

   - Manifest format remains 1.
   - `sample_rate` remains 8000.
   - `initial_unlocked` remains 5.
   - `total_seconds` changes are attributable to SR change? Sam output still targets 8 kHz, so duration remains consistent with current expectations.
   - The generator block names Sam provenance and does not mention the Perth watermark or ARCTIC reference voice.

10. Preserve superseded data per current project policy.

    - Keep the newly generated render as the authoritative repertoire.
    - Archive or annotate superseded Chatterbox artefacts rather than deleting them unasked.
    - Record the render date, seed, checkpoint digest or repo revision, and operator approval in the project memory store when project-state reporting is appropriate.

11. Amend tests only if a separate proposal explicitly revises the schema.

   - Renderer-only work must keep the existing test files unchanged.
   - If the test suite fails, treat that as evidence of a runtime contract violation rather than revising tests first.

12. Open a feature branch and ordinary PR only after full green.

    - Use the repository's normal proposal/branch/PR/pipeline.
    - Do not merge into `main` until the first-pass review and adversarial review are complete.

## Rollback and preservation

- Keep the original Chatterbox manifest and takes until a full Sam generation has verified.
- Do not delete preserve-directory or state-directory content without operator instruction.
- If Sam rendering fails late, restore the verified Chatterbox set and manifest, do not perform partial repairs to mixed-source manifests.
- If tokenization or decoding fails after schema changes, revert to the last verified render, then correct the generator or tests in a separate proposal.
- If resource limits are hit, stop and preserve whatever partial data exists; clean only regenerable artifacts under an explicit operator instruction.

## Files referenced

- `docs/records/maternal-voice-sam-readiness-2026-11-16.md`
- `docs/records/maternal-voice-sam-prosody-design-2026-11-16.md`
- `kaine/modules/audition/maternal_voice.py`
- `kaine/modules/audition/maternal_voice_data/manifest.json`
- `tools/maintainer/generate_maternal_voice.py`
- `tests/test_maternal_voice.py`
- `tests/test_maternal_voice_build_context.py`
- `tests/test_maternal_voice_threads.py`
- `tests/test_stimulus_source_maternal_voice.py`
- `/run/media/erik/2TBm2Store/kaine/qwen3-tts-training/sam-model-v2/checkpoint-epoch-1/README.md`