# Maternal voice unintelligible gate (2026-11-16)

Date: 2026-11-16

Status: record only. No source code, tests, manifest, or generated audio changed.

## Purpose

Define the gate that stops a maternal-voice render from shipping lexical content, and the sequence for converting the Sam render only after the relevant text/prosody tests are green. This record combines three existing constraints:

- content must be unintelligible (prosody-only, no recoverable speech);
- the no-audio prosody checker must pass for every item;
- the Sam regeneration must run only after smoke tests and the established runtime tests pass.

## Unintelligible content gate

The maternal channel is prosody-first. It must provide intonation, rhythm, pitch contour, and vowel-quality drift without words that can be transcribed.

Pass criteria:

- A speech recognizer run over every rendered take yields inconsistent or empty transcripts.
- No take repeats a recognizable lexical phrase or sentence.
- Cross-take transcripts do not agree enough to indicate lexical content.
- A maintainer confirms by listening that no phrase is recoverable.
- The repeated DeCasper/Spence motif remains a prosodic motif, not a recognizable sentence.

Failure of this gate is a content failure, not a tooling failure. The render stops before full regeneration and returns to design or text replacement.

## Prosody gate

The no-audio prosody gate is implemented by:

```text
tools/maintainer/check_maternal_prosody.py
```

An item passes only when all three checks pass:

- syllable density: `syllable_density_ok`
- transient reduction: `transient_ok`
- readability: `readability_ok`
- aggregate: `ok`

Default thresholds:

| Threshold | Constant | Value | Meaning |
|---|---|---|---|
| Maximum syllables per word | `MAX_SYLLABLES_PER_WORD` | `2.0` | No word may exceed 2 syllables. |
| Maximum syllable density | `MAX_SYLLABLE_DENSITY` | `1.8` | Syllables per word, averaged and checked per word. |
| Minimum transient reduction | `MIN_TRANSIENT_REDUCTION` | `0.55` | Consonant-transient reduction must stay at or above this value. |
| Maximum readability (Flesch reading ease) | `MAX_READABILITY` | `40.0` | Text must score at or below 40 Flesch reading-ease units. |

Current lexical texts are expected to fail this gate. Aggregate pass requires final text to pass all three metric checks for all items, with exit status `0` from:

```bash
python tools/maintainer/check_maternal_prosody.py \
  --texts kaine/modules/audition/maternal_voice_data/texts.toml
```

## Readability threshold

Readability is measured as Flesch reading ease. Because lower Flesch scores indicate harder text, `MAX_READABILITY = 40.0` is a ceiling: acceptable text is relatively hard to read.

Important observed behavior from the checker run:

- shipped `texts.toml` scores 0/20 on readability (observed 62.8-119.2);
- a normal sentence such as "The quick brown fox..." scores 94.3 and fails;
- a single very high scoring nonsense sequence can also fail because density dominates rather than readability;
- simple maternal-style phrases naturally score far above 40, so lexical text cannot pass this threshold.

Thus the readability threshold is the dominant failure for lexical content, and passing it requires prosody-first or otherwise low-intelligibility text. It should not be weakened to accommodate lexical sentences.

## Plan: convert Sam render after tests

The Sam conversion is already specified by companion records. This section records the ordered gate after tests before any render mutation.

### Test baseline gate

Before implementation or render work:

1. Run the existing runtime/regression tests:
   - `tests/test_maternal_voice.py`
   - `tests/test_maternal_voice_build_context.py`
   - `tests/test_maternal_voice_threads.py`
   - `tests/test_stimulus_source_maternal_voice.py`
2. Run manifest verification:
   - `python tools/maintainer/generate_maternal_voice.py --verify`
3. Run the prosody checker on the final prosody-first text source and require exit `0`.

### Read-only preflight gate

Before rendering:

1. Verify checkpoint and Sam speaker identity:
   - `sam-model-v2/checkpoint-epoch-1/config.json`
   - `tts_model_type: custom_voice`
   - `spk_id["sam"] == 3000`
2. Verify disk space is at least 30 GiB on the render/model storage.
3. Stop unrelated local models if needed.
4. Confirm no other unexplained repository changes are present.

### Smoke gate before full regeneration

Run these in order. Stop at the first failure and record it.

1. S0 runtime baseline: tests green, manifest verification zero.
2. S1 model load: Sam loads offline and renders one finite waveform with nonzero RMS.
3. S2 single-item render: one item regenerated, manifest hashes verified, all other items reuse-verified.
4. S3 output contract probe: FLAC files are 8 kHz, PCM_16, nonzero frames.
5. S4 determinism replay: rerun produces identical SHA-256 and manifest diff.
6. S5 content intelligibility gate: recognizer output unstable or empty; maintainer finds no recoverable phrase.
7. S6 prosody retention: pitch/intensity contours remain recoverable after 8 kHz resampling.
8. S7 regression tests: all four runtime maternal-voice test files remain green without test edits.

### Full regeneration only after all smoke gates pass

1. Baseline `git status --short`, HEAD, and `--verify`.
2. Confirm checkpoint and storage.
3. Replace text content with prosody-first material and review it before render.
4. Implement Sam renderer in a separate OpenSpec change, keeping runtime and tests untouched.
5. Render one representative item and rerun tests.
6. Run recognizer and prosody probes on that item.
7. Regenerate all 40 takes.
8. Rerun `--verify` and the four runtime maternal-voice tests.
9. Rerun determinism replay and inspect the generator block for honest Sam provenance and no Chatterbox Perth watermark or CMU ARCTIC reference claim.
10. Preserve superseded Chatterbox artefacts rather than deleting them.
11. Open a normal feature-branch PR only after full green, with first-pass and adversarial review.

### Rollback rule

If the Sam render fails late, restore the verified Chatterbox set and manifest. Do not perform partial repairs on a mixed-source manifest. Do not edit tests to make a contract violation pass.

## Companion records

- `docs/records/maternal-voice-sam-prosody-design-2026-11-16.md`
- `docs/records/maternal-voice-sam-readiness-2026-11-16.md`
- `docs/records/maternal-voice-sam-render-plan-2026-11-16.md`
- `docs/records/maternal-sam-conversion-phase2-2026-11-16.md`
- `docs/records/maternal-prosody-check-run-2026-11-16.md`
- `docs/records/maternal-prosody-smoke-plan-2026-11-16.md`
- `docs/records/maternal-prosody-fixture-plan-2026-11-16.md`

Return changed path: `/var/home/erik/Projects/kaineone/kaine/docs/records/maternal-voice-unintelligible-gate-2026-11-16.md`.
