# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Verify that the old 'Some memories come back to me.' sentence is gone (PR 3, task 5.4)."""

from kaine.faithful.felt import _f_episodic_memory_recall


OLD_SENTENCE = "Some memories come back to me."


def test_no_old_sentence_with_count():
    payload = {"count": 3, "familiarity": "somewhat_familiar", "top_similarity": 0.8}
    result = _f_episodic_memory_recall(payload)
    assert result != OLD_SENTENCE


def test_no_old_sentence_with_high_count():
    payload = {"count": 100, "familiarity": "familiar", "top_similarity": 0.95}
    result = _f_episodic_memory_recall(payload)
    assert result != OLD_SENTENCE


def test_no_old_sentence_with_invalid_count():
    payload = {"count": True}
    result = _f_episodic_memory_recall(payload)
    assert result != OLD_SENTENCE


def test_no_old_sentence_anywhere():
    """No possible input should produce the old sentence."""
    for count in [1, 5, 10, 50]:
        for fam in ["faintly_familiar", "somewhat_familiar", "familiar"]:
            payload = {"count": count, "familiarity": fam, "top_similarity": 0.5}
            result = _f_episodic_memory_recall(payload)
            assert result != OLD_SENTENCE, f"old sentence returned for count={count}, familiarity={fam}"


def test_remember_only_with_content():
    """'I remember' only appears when content is present."""
    payload_no_content = {"count": 3, "familiarity": "somewhat_familiar", "top_similarity": 0.8}
    result = _f_episodic_memory_recall(payload_no_content)
    assert "I remember" not in result

    payload_with_content = {
        "count": 3,
        "familiarity": "somewhat_familiar",
        "top_similarity": 0.8,
        "content": {
            "members": [{"source": "affect", "type": "affect.emotion", "felt_fields": {"emotion": "joy"}}],
            "age_band": "this_wake",
            "trace_ref": "pt-1",
        },
    }
    result = _f_episodic_memory_recall(payload_with_content)
    assert "I remember" in result
