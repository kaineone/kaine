# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the recalled-content rendering in the felt template set (PR 3, task 5.4)."""

from typing import Any

from kaine.faithful.felt import (
    AGE_PHRASES,
    PAST_TENSE_TEMPLATES,
    _f_episodic_memory_recall,
    _f_episodic_memory_replay,
)


def _recall_payload(
    count: Any = 3,
    content: dict[str, Any] | None = None,
    familiarity: str = "somewhat_familiar",
    top_similarity: float = 0.8,
) -> dict[str, Any]:
    p: dict[str, Any] = {
        "count": count,
        "collection": "episodic",
        "query_length": 100,
        "max_affect_intensity": 0.3,
        "top_similarity": top_similarity,
        "familiarity": familiarity,
    }
    if content is not None:
        p["content"] = content
    return p


def _content(members: list[dict[str, Any]], age_band: str = "this_wake") -> dict[str, Any]:
    return {"members": members, "age_band": age_band, "trace_ref": "pt-1"}


# -- Content rendering --------------------------------------------------------


def test_recall_with_vision_member():
    members = [{"source": "vision", "type": "vision.report", "felt_fields": {"change_score": 0.1}}]
    result = _f_episodic_memory_recall(_recall_payload(content=_content(members)))
    assert result.startswith("I remember from earlier today:")
    assert "What I saw" in result


def test_recall_with_multiple_members():
    members = [
        {"source": "affect", "type": "affect.state", "felt_fields": {"state": {"arousal": 0.7, "valence": 0.5}}},
        {"source": "vision", "type": "vision.report", "felt_fields": {"change_score": 0.03}},
    ]
    result = _f_episodic_memory_recall(_recall_payload(content=_content(members)))
    assert result.startswith("I remember from earlier today:")
    assert "I felt" in result
    assert "What I saw" in result


def test_recall_age_band_earlier():
    members = [{"source": "affect", "type": "affect.emotion", "felt_fields": {"emotion": "joy"}}]
    result = _f_episodic_memory_recall(_recall_payload(content=_content(members, age_band="earlier")))
    assert "from long ago" in result


def test_recall_age_band_before_last_sleep():
    members = [{"source": "affect", "type": "affect.emotion", "felt_fields": {"emotion": "joy"}}]
    result = _f_episodic_memory_recall(_recall_payload(
        content=_content(members, age_band="before_last_sleep"),
    ))
    assert "from before my last rest" in result


def test_recall_unknown_member_type():
    members = [{"source": "unknown_src", "type": "unknown_type"}]
    result = _f_episodic_memory_recall(_recall_payload(content=_content(members)))
    assert "I remember a moment I cannot make out." in result


def test_recall_zero_count():
    result = _f_episodic_memory_recall(_recall_payload(count=0))
    assert result == "Nothing comes back to me from memory."


def test_recall_invalid_count():
    result = _f_episodic_memory_recall(_recall_payload(count=True))
    assert result == "Something stirs in my memories."


def test_recall_digit_guard_on_content():
    """A digit in a past-tense line triggers the fallback via _guarded."""
    for (src, typ), fn in PAST_TENSE_TEMPLATES.items():
        line = fn({"change_score": 999.0, "normalised_error": 999.0, "wellness": 999.0})
        assert not any(ch.isdigit() for ch in line), f"digit leaked in {src}/{typ}: {line}"


# -- Replay rendering --------------------------------------------------------


def test_replay_with_members():
    payload = {
        "memory_id": "pt-1",
        "text": "some text",
        "members": [
            {"source": "affect", "type": "affect.emotion", "felt_fields": {"emotion": "joy"}},
        ],
    }
    result = _f_episodic_memory_replay(payload)
    assert result.startswith("As I rest, I go over a memory:")
    assert "I felt joy." in result


def test_replay_without_members():
    payload = {"memory_id": "pt-1", "text": "some text"}
    result = _f_episodic_memory_replay(payload)
    assert result == "I am going over a memory."


def test_replay_unknown_member_type():
    payload = {
        "memory_id": "pt-1",
        "text": "some text",
        "members": [{"source": "x", "type": "y"}],
    }
    result = _f_episodic_memory_replay(payload)
    assert "I remember a moment I cannot make out." in result


# -- Past-tense template coverage --------------------------------------------


def test_past_tense_templates_exist_for_key_types():
    expected_keys = {
        ("vision", "vision.report"),
        ("audition", "audition.perception"),
        ("interoception", "interoception.report"),
        ("affect", "affect.state"),
        ("affect", "affect.emotion"),
        ("sequence", "sequence.report"),
    }
    assert set(PAST_TENSE_TEMPLATES.keys()) == expected_keys


def test_age_phrases_cover_all_bands():
    assert set(AGE_PHRASES.keys()) == {"this_wake", "before_last_sleep", "earlier"}


def test_past_vision_empty_payload():
    fn = PAST_TENSE_TEMPLATES[("vision", "vision.report")]
    assert fn({}) == "I was looking."


def test_past_audition_empty_payload():
    fn = PAST_TENSE_TEMPLATES[("audition", "audition.perception")]
    assert fn({}) == "I was listening."


def test_past_interoception_empty_payload():
    fn = PAST_TENSE_TEMPLATES[("interoception", "interoception.report")]
    assert fn({}) == "I sensed my body."


def test_past_affect_state_empty_payload():
    fn = PAST_TENSE_TEMPLATES[("affect", "affect.state")]
    assert fn({}) == "I felt my mood."


def test_past_affect_emotion_empty_payload():
    fn = PAST_TENSE_TEMPLATES[("affect", "affect.emotion")]
    assert fn({}) == "I felt something I could not name."


def test_past_sequence_empty_payload():
    fn = PAST_TENSE_TEMPLATES[("sequence", "sequence.report")]
    assert fn({}) == "Time was moving on."
