# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for kaine.modules.language.repetition.cut_text."""

from __future__ import annotations

import random

from kaine.modules.language.repetition import (
    CUT_REPEATED_SENTENCE,
    CUT_TOKEN_CAP,
    REPEAT_MIN_WORDS,
    cut_text,
)


def test_real_loop_repeated_sentence() -> None:
    intro = (
        "I do not know how I feel. "
        "I do not know what I am feeling. "
        "I do not know what I am thinking. "
        "I do not know what I am thinking about. "
    )
    text = intro + "I do not know what I am thinking about. " * 20 + "I do not know what I"
    result, reason = cut_text(text, stopped_by_cap=True)
    assert result == intro.rstrip()
    assert reason == CUT_REPEATED_SENTENCE


def test_simple_repeated_sentence() -> None:
    result, reason = cut_text("I am thinking clearly. I am thinking clearly.", stopped_by_cap=True)
    assert result == "I am thinking clearly."
    assert reason == CUT_REPEATED_SENTENCE


def test_short_repeat_is_unchanged() -> None:
    text = "No. No. I am here."
    result, reason = cut_text(text, stopped_by_cap=True)
    assert result is text
    assert reason is None


def test_case_and_whitespace_preserved_before_cut() -> None:
    result, reason = cut_text("I am  here now. i am here now!", stopped_by_cap=True)
    assert result == "I am  here now."
    assert reason == CUT_REPEATED_SENTENCE


def test_list_marker_lines() -> None:
    text = (
        "- I feel it in my chest.\n"
        "- I feel it in my hands.\n"
        "- I feel it in my chest.\n"
        "- more"
    )
    result, reason = cut_text(text, stopped_by_cap=True)
    assert result == "- I feel it in my chest.\n- I feel it in my hands."
    assert reason == CUT_REPEATED_SENTENCE


def test_newline_lines_with_trailing_newline() -> None:
    text = "I am here\nI am listening\nI am here\n"
    result, reason = cut_text(text, stopped_by_cap=True)
    assert result == "I am here\nI am listening"
    assert reason == CUT_REPEATED_SENTENCE


def test_newline_lines_with_open_tail_unchanged() -> None:
    text = "I am here\nI am listening\nI am here"
    result, reason = cut_text(text, stopped_by_cap=False)
    assert result is text
    assert reason is None


def test_formatting_before_cut_is_preserved() -> None:
    text = "A quiet room is here.\n\nI am waiting for something. I am waiting for something."
    result, reason = cut_text(text, stopped_by_cap=True)
    assert result == "A quiet room is here.\n\nI am waiting for something."
    assert reason == CUT_REPEATED_SENTENCE


def test_token_cap_cuts_open_tail() -> None:
    result, reason = cut_text("I am here. I feel the", stopped_by_cap=True)
    assert result == "I am here."
    assert reason == CUT_TOKEN_CAP


def test_token_cap_does_not_cut_when_not_stopped() -> None:
    text = "I am here. I feel the"
    result, reason = cut_text(text, stopped_by_cap=False)
    assert result is text
    assert reason is None


def test_token_cap_no_complete_sentence_unchanged() -> None:
    text = "I feel the"
    result, reason = cut_text(text, stopped_by_cap=True)
    assert result is text
    assert reason is None


def test_token_cap_exact_sentence_end_unchanged() -> None:
    text = "I am here."
    result, reason = cut_text(text, stopped_by_cap=True)
    assert result is text
    assert reason is None


def test_empty_string() -> None:
    for stopped_by_cap in (True, False):
        result, reason = cut_text("", stopped_by_cap=stopped_by_cap)
        assert result == ""
        assert reason is None


def test_min_words_default_cuts_three_word_repeat() -> None:
    result, reason = cut_text("It is fine. It is fine.", stopped_by_cap=True)
    assert result == "It is fine."
    assert reason == CUT_REPEATED_SENTENCE


def test_min_words_custom_ignores_short_repeat() -> None:
    text = "It is fine. It is fine."
    result, reason = cut_text(text, stopped_by_cap=True, min_words=4)
    assert result is text
    assert reason is None


def test_repeat_min_words_value() -> None:
    assert REPEAT_MIN_WORDS == 3


def test_no_repeat_after_cut_property() -> None:
    sentences = [
        "I am here.",
        "I feel it.",
        "It is fine.",
        "No.",
        "Wait.",
        "And you?",
    ]
    rng = random.Random(0)
    for _ in range(500):
        count = rng.randint(1, 12)
        parts = [rng.choice(sentences) for _ in range(count)]
        sep = rng.choice([" ", "\n", "  ", "\n\n"])
        text = sep.join(parts)
        if rng.choice([True, False]):
            text = text + "and then I"
        for stopped_by_cap in (True, False):
            result, _reason = cut_text(text, stopped_by_cap=stopped_by_cap)
            assert text.startswith(result)
            recut, rereason = cut_text(result, stopped_by_cap=False)
            assert rereason is None
            assert recut is result
            assert cut_text(result, stopped_by_cap=False)[1] is None


def test_list_marker_is_ignored_in_comparison() -> None:
    result, reason = cut_text(
        "- I am here now.\nI am here now.", stopped_by_cap=False
    )
    assert result == "- I am here now."
    assert reason == CUT_REPEATED_SENTENCE

    result, reason = cut_text(
        "1. I feel the quiet.\n2) I feel the quiet.", stopped_by_cap=False
    )
    assert result == "1. I feel the quiet."
    assert reason == CUT_REPEATED_SENTENCE
