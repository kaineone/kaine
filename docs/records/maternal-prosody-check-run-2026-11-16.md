# Maternal prosody check run (2026-11-16)

## Test suite

Command: `pytest -q tests/test_maternal_prosody_check.py`
Result: 5 passed, 0 failed, 0 errors (0.11s).
Warnings: pytest-asyncio deprecation only.

## CLI checks

- `--texts kaine/modules/audition/maternal_voice_data/texts.toml`: exit 1; 20 items checked.
  - syllable-density check: 16/20 pass; 4 fail due per-word syllable cap (words > 2 syllables, e.g. "tomorrow").
  - consonant-transient reduction: 20/20 pass (min 0.55; observed 0.64-0.92).
  - readability (Flesch <= 40): 0/20 pass (observed 62.8-119.2).
- `--file` temp file ("ba ba ba"): exit 1; density=1.00, reduction=0.50, readability=119.2.
  - reduction 0.50 < 0.55, so fails transient check only.
- `--text "supercalifragilistic expialidocious"`: exit 1; density=6.50 (per-word 8/5 syllables), reduction=0.62, readability=-345.1.
- `--text "The quick brown fox..."`: exit 1; density=1.22, reduction=0.63, readability=94.3.
- empty stdin: exit 2 ("no input").

## Threshold edge cases

- Default thresholds: max syllable density 1.8, max syllables/word 2.0, min transient reduction 0.55, max Flesch reading ease 40.0.
- Because readability is measured as Flesch reading-ease, simple maternal phrases score 62-119 and never satisfy the <= 40 default, so any aggregate `check_prosody`/`check_text` call on these phrases returns False.
- Aggregate result for the shipped `texts.toml`: 0/20 items pass all three checks; only density failures are per-word (passage words with 3 syllables) and readability is the dominant failure.
- Empty input yields CLI exit 2, distinct from check failure (exit 1).
- `check_syllable_density` applies both an average density cap and a per-word cap; passing only one can still fail due the other.