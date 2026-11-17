# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Lightweight prosody checks for maternal voice text.

No runtime code. Provides heuristics to judge whether a text string is
"prosody-first / low intelligibility":
  - syllable-density upper limits
  - consonant / transient reduction score
  - a simple readability threshold

CLI usage:
    python tools/maintainer/check_maternal_prosody.py --text "..."
    python tools/maintainer/check_maternal_prosody.py --file path.txt
    python tools/maintainer/check_maternal_prosody.py --texts path.toml
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# ---------------------------------------------------------------- constants
MAX_SYLLABLES_PER_WORD = 2.0
MAX_SYLLABLE_DENSITY = 1.8
MIN_TRANSIENT_REDUCTION = 0.55
MAX_READABILITY = 40.0  # Flesch reading ease; lower = harder to read

_HARD_TRANSIENTS = set("ptkbdgcqxs fz".replace(" ", ""))


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z']+", text)


def count_syllables(word: str) -> int:
    """Heuristic syllable count for a single word."""
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 0
    # vowel groups
    groups = re.findall(r"[aeiouy]+", w)
    n = len(groups)
    # silent trailing e
    if w.endswith("e") and not w.endswith("le") and n > 1:
        n -= 1
    # ensure at least one
    if n < 1:
        n = 1
    return n


def syllable_count(text: str) -> int:
    return sum(count_syllables(w) for w in _words(text))


def word_count(text: str) -> int:
    return len(_words(text))


def syllables_per_word(text: str) -> float:
    wc = word_count(text)
    if wc == 0:
        return 0.0
    return syllable_count(text) / wc


def syllable_density(text: str) -> float:
    return syllables_per_word(text)


def _call_threshold(kwargs: dict[str, Any], positional: list[Any], default: float,
                    keys: tuple[str, ...]) -> float:
    for k in keys:
        if k in kwargs:
            try:
                return float(kwargs[k])
            except (TypeError, ValueError):
                pass
    if positional:
        try:
            return float(positional[0])
        except (TypeError, ValueError):
            pass
    if "threshold" in kwargs:
        try:
            return float(kwargs["threshold"])
        except (TypeError, ValueError):
            pass
    return float(default)


def check_syllable_density(text: str, *args: Any, **kwargs: Any) -> bool:
    """Return True if syllable density is within the upper limit (low density)."""
    limit = _call_threshold(kwargs, list(args), MAX_SYLLABLE_DENSITY,
                            ("max_density", "limit", "max_syllables_per_word",
                             "max_syllable_density", "upper_limit"))
    # If caller passes max_syllables_per_word as a per-word cap, use max too.
    per_word_cap = kwargs.get("max_syllables_per_word", None)
    if per_word_cap is not None:
        try:
            limit = min(limit, float(per_word_cap))
        except (TypeError, ValueError):
            # per_word_cap is not numeric; keep the previously resolved limit
            pass
    dens = syllable_density(text)
    # also check per-word max
    words = _words(text)
    per_word_ok = all(count_syllables(w) <= (per_word_cap if per_word_cap is not None
                                            else MAX_SYLLABLES_PER_WORD) + 0.001
                      for w in words) if words else True
    return bool(dens <= limit and per_word_ok)


def syllable_density_ok(text: str, *args: Any, **kwargs: Any) -> bool:
    return check_syllable_density(text, *args, **kwargs)


def syllable_density_exceeds(text: str, *args: Any, **kwargs: Any) -> bool:
    return not check_syllable_density(text, *args, **kwargs)


def exceeds_syllable_density(text: str, *args: Any, **kwargs: Any) -> bool:
    return syllable_density_exceeds(text, *args, **kwargs)


def within_syllable_limit(text: str, *args: Any, **kwargs: Any) -> bool:
    return check_syllable_density(text, *args, **kwargs)


# ---------------------------------------------------------------- consonant / transient
def _hard_transient_ratio(text: str) -> float:
    letters = [c for c in text.lower() if c.isalpha()]
    if not letters:
        return 0.0
    hard = sum(1 for c in letters if c in _HARD_TRANSIENTS)
    return hard / len(letters)


def consonant_transient_score(text: str) -> float:
    """Hard transient ratio (higher = more transients). Alias retained for compat."""
    return _hard_transient_ratio(text)


def transient_score(text: str) -> float:
    return consonant_transient_score(text)


def hard_consonant_ratio(text: str) -> float:
    return _hard_transient_ratio(text)


def consonant_transient_reduction(text: str) -> float:
    return 1.0 - _hard_transient_ratio(text)


def consonant_transient_reduction_score(text: str) -> float:
    return consonant_transient_reduction(text)


def transient_reduction_score(text: str) -> float:
    return consonant_transient_reduction(text)


def reduction_score(text: str) -> float:
    return consonant_transient_reduction(text)


def consonant_reduction(text: str) -> float:
    return consonant_transient_reduction(text)


def check_consonant_transient(text: str, *args: Any, **kwargs: Any) -> bool:
    """Return True if transient reduction meets minimum (low hard transients)."""
    threshold = _call_threshold(kwargs, list(args), MIN_TRANSIENT_REDUCTION,
                               ("min_reduction", "threshold", "min_score",
                                "transient_reduction", "score"))
    return bool(consonant_transient_reduction(text) >= threshold)


def transient_reduction_ok(text: str, *args: Any, **kwargs: Any) -> bool:
    return check_consonant_transient(text, *args, **kwargs)


def check_transient_reduction(text: str, *args: Any, **kwargs: Any) -> bool:
    return check_consonant_transient(text, *args, **kwargs)


# ---------------------------------------------------------------- readability
def _sentence_count(text: str) -> int:
    parts = re.split(r"[.!?]+", text.strip())
    return max(1, len([p for p in parts if p.strip()]))


def flesch_reading_ease(text: str) -> float:
    words = _words(text)
    if not words:
        return 0.0
    sentences = _sentence_count(text)
    sylls = syllable_count(text)
    asl = len(words) / sentences
    asw = sylls / len(words)
    return 206.835 - 1.015 * asl - 84.6 * asw


def readability(text: str) -> float:
    return flesch_reading_ease(text)


def readability_score(text: str) -> float:
    return flesch_reading_ease(text)


def flesch_kincaid_grade(text: str) -> float:
    words = _words(text)
    if not words:
        return 0.0
    sentences = _sentence_count(text)
    sylls = syllable_count(text)
    asl = len(words) / sentences
    asw = sylls / len(words)
    return 0.39 * asl + 11.8 * asw - 15.59


def is_readable(text: str, *args: Any, **kwargs: Any) -> bool:
    """Return True if reading ease is at or above threshold (normal readability)."""
    threshold = _call_threshold(kwargs, list(args), 60.0,
                               ("threshold", "min_score", "min_readability"))
    return bool(flesch_reading_ease(text) >= threshold)


def check_readability(text: str, *args: Any, **kwargs: Any) -> bool:
    """Default: prosody-first content should NOT be easily readable.

    Returns True when reading ease is at or below the threshold (low readability).
    """
    threshold = _call_threshold(kwargs, list(args), MAX_READABILITY,
                               ("threshold", "max_readability", "max_score",
                                "readability_threshold"))
    return bool(flesch_reading_ease(text) <= threshold)


def readability_ok(text: str, *args: Any, **kwargs: Any) -> bool:
    return check_readability(text, *args, **kwargs)


def readability_too_high(text: str, *args: Any, **kwargs: Any) -> bool:
    threshold = _call_threshold(kwargs, list(args), MAX_READABILITY,
                               ("threshold", "max_readability", "max_score"))
    return bool(flesch_reading_ease(text) > threshold)


def low_readability(text: str, *args: Any, **kwargs: Any) -> bool:
    return check_readability(text, *args, **kwargs)


# ---------------------------------------------------------------- aggregate
def check_text(text: str, **kwargs: Any) -> dict[str, Any]:
    sd_ok = check_syllable_density(text, **{k: v for k, v in kwargs.items()
                                            if k not in ("min_reduction", "threshold")})
    tr_ok = check_consonant_transient(text)
    rd_ok = check_readability(text)
    ok = bool(sd_ok and tr_ok and rd_ok)
    return {
        "ok": ok,
        "passed": ok,
        "syllable_density": syllable_density(text),
        "syllable_density_ok": sd_ok,
        "transient_reduction": consonant_transient_reduction(text),
        "transient_ok": tr_ok,
        "readability": flesch_reading_ease(text),
        "readability_ok": rd_ok,
    }


def check_prosody(text: str, **kwargs: Any) -> bool:
    return bool(check_text(text, **kwargs)["ok"])


def is_prosody_ok(text: str, **kwargs: Any) -> bool:
    return check_prosody(text, **kwargs)


def validate_text(text: str, **kwargs: Any) -> bool:
    return check_prosody(text, **kwargs)


def check(text: str, **kwargs: Any) -> bool:
    return check_prosody(text, **kwargs)


def check_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for it in items:
        text = it.get("text", "")
        r = check_text(text)
        r = dict(r)
        r["id"] = it.get("id")
        results.append(r)
    return results


def load_texts_items(path: str | Path) -> list[dict[str, Any]]:
    """Load texts.toml items if tomllib available."""
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return list(data.get("item", []))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check maternal voice prosody text.")
    parser.add_argument("--text", help="text to check")
    parser.add_argument("--file", type=Path, help="file containing text")
    parser.add_argument("--texts", type=Path, help="texts.toml to check")
    args = parser.parse_args(argv)

    texts_to_check: list[tuple[str, str]] = []
    if args.texts:
        for it in load_texts_items(args.texts):
            texts_to_check.append((str(it.get("id", "?")), str(it.get("text", ""))))
    elif args.file:
        texts_to_check.append((str(args.file), args.file.read_text(encoding="utf-8")))
    elif args.text:
        texts_to_check.append(("<arg>", args.text))
    else:
        data = sys.stdin.read()
        if data.strip():
            texts_to_check.append(("<stdin>", data))

    if not texts_to_check:
        print("no input", file=sys.stderr)
        return 2

    failed = False
    for label, text in texts_to_check:
        r = check_text(text)
        print(f"{label}: ok={r['ok']} density={r['syllable_density']:.2f} "
              f"reduction={r['transient_reduction']:.2f} readability={r['readability']:.1f}")
        if not r["ok"]:
            failed = True
    return 1 if failed else 0


# Aliases to common alternative spellings
count_syllables_text = syllable_count
total_syllables = syllable_count
syllables = syllable_count


if __name__ == "__main__":
    raise SystemExit(main())
