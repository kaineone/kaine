# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Detect and cut self-reinforcing repetition in generated language text.

Once a sentence repeats verbatim, subsequent repetitions carry no new
information, and fragments cut by a token cap are not finished sentences.
This module provides ``cut_text`` to remove such trailing material.
"""

from __future__ import annotations

import re
from typing import Optional

REPEAT_MIN_WORDS = 3
CUT_REPEATED_SENTENCE = "repeated_sentence"
CUT_TOKEN_CAP = "token_cap"

_SENTENCE_END = re.compile(r"[.!?]+[\"')\]’”]*(?=\s|$)|\n")
_LIST_MARKER = re.compile(r"^(?:[-*•]|\d+[.)])\s+")
_TRAILING_PUNCTUATION = frozenset(".!?\"')]" + "\u2019\u201d")


def _sentence_key(sentence: str, min_words: int) -> Optional[str]:
    """Return the comparison key for *sentence*, or ``None`` if too short."""
    sentence = sentence.strip()
    sentence = _LIST_MARKER.sub("", sentence)
    while sentence and sentence[-1] in _TRAILING_PUNCTUATION:
        sentence = sentence[:-1]
    sentence = " ".join(sentence.split())
    key = sentence.casefold()
    if len(key.split()) < min_words:
        return None
    return key


def cut_text(
    text: str,
    *,
    stopped_by_cap: bool,
    min_words: int = REPEAT_MIN_WORDS,
) -> tuple[str, Optional[str]]:
    """Return ``(cut_text, reason)`` with trailing problematic text removed.

    Sentences are split by sentence-ending punctuation followed by whitespace
    or the end of the string, or by a newline. The first sentence whose
    normalized key (stripped, list-marker and trailing punctuation removed,
    whitespace collapsed, case-folded) repeats a previous sentence of at least
    ``min_words`` words is cut, returning ``CUT_REPEATED_SENTENCE``.

    If no repeat is found and ``stopped_by_cap`` is true, any non-whitespace
    open tail after the last complete sentence is cut, returning
    ``CUT_TOKEN_CAP``.

    If nothing is cut, the input string object is returned unchanged and the
    reason is ``None``. The function never raises for string input.
    """
    seen: set[str] = set()
    start = 0
    last_end = 0
    found_sentence = False

    for match in _SENTENCE_END.finditer(text):
        end = match.end()
        span = text[start:end]
        if not span.strip():
            start = end
            continue

        found_sentence = True
        key = _sentence_key(span, min_words)
        if key is not None:
            if key in seen:
                leading_whitespace = len(span) - len(span.lstrip())
                cut_start = start + leading_whitespace
                return (text[:cut_start].rstrip(), CUT_REPEATED_SENTENCE)
            seen.add(key)

        last_end = end
        start = end

    if stopped_by_cap and found_sentence:
        tail = text[start:]
        if tail.strip():
            return (text[:last_end].rstrip(), CUT_TOKEN_CAP)

    return (text, None)
