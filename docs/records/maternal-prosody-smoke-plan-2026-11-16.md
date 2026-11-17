# Maternal prosody smoke plan: no-audio text checks

Date: 2026-11-16

Status: smoke plan only. No source code, tests, manifest, generated audio, or texts are changed by this document.

## Purpose

Provide a no-audio smoke pass for the maternal-voice texts before or after a render. It checks the prosody-first text gates implemented in `tools/maintainer/check_maternal_prosody.py` without decoding or playing any FLAC takes. It is intended for use on existing generated takes' source text (`texts.toml`) and any candidate replacement text.

## Inputs

- Texts file: `kaine/modules/audition/maternal_voice_data/texts.toml`
- Checker: `tools/maintainer/check_maternal_prosody.py`
- Thresholds in the checker:
  - `MAX_SYLLABLE_DENSITY = 1.8` (syllables per word)
  - `MAX_SYLLABLES_PER_WORD = 2.0`
  - `MIN_TRANSIENT_REDUCTION = 0.55`
  - `MAX_READABILITY = 40.0` (Flesch reading ease ceiling; lower is harder to read)

The aggregate `check_text` result is the gate. An item passes only when all of the following are true:

- `syllable_density_ok` is true.
- `transient_ok` is true.
- `readability_ok` is true.
- `ok` is true.

## No-audio smoke command

```bash
set -eu
REPO=/var/home/erik/Projects/kaineone/kaine
cd "$REPO"
python tools/maintainer/check_maternal_prosody.py \
  --texts kaine/modules/audition/maternal_voice_data/texts.toml
```

Expected exit status when all items are prosody-first: `0`.

Current lexical texts are expected to fail this gate, primarily through `readability_ok` and possibly `transient_ok`. A failure exit status of `1` is therefore not by itself an implementation failure; it is the intended signal that lexical content remains in the source.

## Per-item diagnostic command

```bash
set -eu
REPO=/var/home/erik/Projects/kaineone/kaine
cd "$REPO"
python tools/maintainer/check_maternal_prosody.py --text "REPLACE WITH CANDIDATE TEXT"
```

## Input and output examples

Example 1, aggregate failure on a normal sentence:

Input:

```text
The quick brown fox jumps over the lazy dog.
```

Command:

```bash
python tools/maintainer/check_maternal_prosody.py --text "The quick brown fox jumps over the lazy dog."
```

Representative output:

```text
<arg>: ok=False density=1.22 reduction=0.63 readability=94.3
```

Interpretation: syllable density is acceptable, but readability is far above the 40.0 prosody-first ceiling and transient reduction is below 0.55, so the text fails.

Example 2, low syllable density but excessive readability:

Input:

```text
ba ba ba
```

Command:

```bash
python tools/maintainer/check_maternal_prosody.py --text "ba ba ba"
```

Representative output:

```text
<arg>: ok=False density=1.00 reduction=0.50 readability=119.2
```

Interpretation: density is low, but the hard-consonant/transient reduction is 0.50, below the 0.55 threshold, and the text remains too readable.

Example 3, individual gate illustrations:

Input and resulting component checks:

```text
text = "aaaa mmmm llll"
syllable_density      = 1.00  -> pass (<= 1.8)
transient_reduction   = 1.00  -> pass (>= 0.55)
readability           = 119.2 -> fail (> 40.0)
ok                    = False
```

```text
text = "supercalifragilistic expialidocious"
syllable_density      = 6.50  -> fail (> 1.8)
transient_reduction   = 0.62  -> pass (>= 0.55)
readability           = -345.1 -> pass (<= 40.0)
ok                    = False
```

Example 4, aggregate pass on a long soft-syllable run:

Input:

```text
ma ma ma ... (90 repetitions of "ma")
```

Command shape:

```bash
python tools/maintainer/check_maternal_prosody.py --text "$(python -c "print('ma '*90)")"
```

Representative output:

```text
<arg>: ok=True density=1.00 reduction=1.00 readability=30.9
```

Interpretation: all three gates pass. This is an illustrative shape, not a recommended content template; candidate maternal prosody strings still require manual maintainer review for recoverability.

## Relation to the intelligibility threshold

The readability gate (`MAX_READABILITY = 40.0`) is the text-side proxy for the prosody intelligibility requirement: prosody-first content should not be easily readable. The audio-side counterpart is smoke gate S5 in `docs/records/maternal-voice-sam-render-plan-2026-11-16.md`, where a speech recognizer is run over rendered takes and expected to produce unstable or empty transcripts. This no-audio plan does not replace S5; it filters candidate text before any audio is rendered or decoded.

## Pass criteria for a candidate text set

1. Every item in `texts.toml` returns `ok=True`.
2. Every item has `syllable_density <= 1.8`.
3. Every item has `transient_reduction >= 0.55`.
4. Every item has `readability <= 40.0`.
5. A maintainer confirms that no lexical phrase is recoverable.
6. No source, test, manifest, audio, or texts file is modified by running this plan.

## Companion records

- `docs/records/maternal-voice-sam-prosody-design-2026-11-16.md`
- `docs/records/maternal-voice-sam-readiness-2026-11-16.md`
- `docs/records/maternal-voice-sam-render-plan-2026-11-16.md`