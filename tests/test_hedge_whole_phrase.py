# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from kaine.evaluation.affect_correlation import _normalize_text, output_characteristics


def test_no_hedge_in_substrings():
    assert output_characteristics("A mighty wave disappears; rain is unlikely.")["hedge_word_count"] == 0


def test_counts_distinct_hedge_phrases():
    assert output_characteristics("I might go. It appears likely, and I might stay.")["hedge_word_count"] == 3


def test_case_insensitive_and_punctuation_boundary():
    assert output_characteristics("Perhaps.")["hedge_word_count"] == 1
    assert output_characteristics("PERHAPS")["hedge_word_count"] == 1


def test_multiword_hedge_with_smart_quote():
    assert output_characteristics("I’m not sure, I think so")["hedge_word_count"] == 1


def test_multiword_hedge_across_whitespace_runs():
    assert output_characteristics("I   think it is   kind of   nice")["hedge_word_count"] == 2


def test_hyphen_boundary_and_suffix_exclusion():
    assert output_characteristics("maybe-later")["hedge_word_count"] == 1
    assert output_characteristics("maybes")["hedge_word_count"] == 0


def test_normalize_text():
    assert _normalize_text("Ａ B’c  “D”") == "a b'c \"d\""
