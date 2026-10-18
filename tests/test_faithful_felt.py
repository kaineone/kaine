# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import math
from datetime import datetime, timezone

import pytest

from kaine.bus import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.faithful.felt import (
    ANOMALY_WORDS,
    AROUSAL_WORDS,
    CERTAINTY_WORDS,
    CHANGE_WORDS,
    DOMINANCE_WORDS,
    DRIVE_LEVEL_WORDS,
    FAMILIARITY_WORDS,
    FATIGUE_DEFAULT_THRESHOLD,
    FATIGUE_WORDS,
    FELT_TEMPLATES,
    INTERACTION_WORDS,
    PREDICTION_ERROR_WORDS,
    SURPRISE_WORDS,
    VALENCE_WORDS,
    WELLNESS_WORDS,
    felt_event_phrase,
    felt_renderer,
    grade,
    redact_heard_speech_felt,
)
from kaine.faithful.renderer import FaithfulRenderer
from kaine.faithful.templates import STRONG_DRIVE_BAND, TEMPLATES, redact_heard_speech


def _ev(source, type_, payload):
    return Event(
        source=source,
        type=type_,
        payload=payload,
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
        causal_parent=None,
    )


BIN_TABLES = [
    ("change", CHANGE_WORDS),
    ("familiarity", FAMILIARITY_WORDS),
    ("surprise", SURPRISE_WORDS),
    ("prediction_error", PREDICTION_ERROR_WORDS),
    ("wellness", WELLNESS_WORDS),
    ("fatigue", FATIGUE_WORDS),
    ("arousal", AROUSAL_WORDS),
    ("valence", VALENCE_WORDS),
    ("dominance", DOMINANCE_WORDS),
    ("anomaly", ANOMALY_WORDS),
    ("drive_level", DRIVE_LEVEL_WORDS),
    ("interaction", INTERACTION_WORDS),
    ("certainty", CERTAINTY_WORDS),
]


@pytest.mark.parametrize("name, table", BIN_TABLES)
def test_bin_edges(name, table):
    for i in range(len(table) - 1):
        edge = table[i][0]
        if math.isfinite(edge):
            assert grade(edge - 1e-9, table) == table[i][1]
            assert grade(edge, table) == table[i + 1][1]
    assert grade(1e9, table) == table[-1][1]


def test_bin_table_literal_values():
    assert CHANGE_WORDS == ((0.01, "barely changing"), (0.05, "changing a little"), (0.2, "changing noticeably"), (math.inf, "changing sharply"))
    assert FAMILIARITY_WORDS == ((0.3, "new to me"), (0.7, "somewhat familiar"), (math.inf, "familiar"))
    assert SURPRISE_WORDS == ((0.5, "faintly"), (0.7, "noticeably"), (0.85, "strongly"), (math.inf, "sharply"))
    assert PREDICTION_ERROR_WORDS == ((0.75, "as I expected"), (1.5, "a little unexpected"), (3.0, "unexpected"), (math.inf, "very unexpected"))
    assert WELLNESS_WORDS == ((0.4, "unwell"), (0.7, "a little off"), (0.9, "well"), (math.inf, "very well"))
    assert FATIGUE_WORDS == ((0.25, "rested"), (0.5, "a little tired"), (0.8, "tired"), (math.inf, "very tired"))
    assert AROUSAL_WORDS == ((0.2, "very calm"), (0.4, "calm"), (0.6, "alert"), (0.8, "stirred up"), (math.inf, "very stirred up"))
    assert VALENCE_WORDS == ((-0.5, "bad"), (-0.15, "a little low"), (0.15, "neither good nor bad"), (0.5, "good"), (math.inf, "very good"))
    assert DOMINANCE_WORDS == ((-0.5, "helpless"), (-0.15, "a little unsure of myself"), (0.15, "steady"), (0.5, "in control"), (math.inf, "firmly in control"))
    assert ANOMALY_WORDS == ((1.0, "steady"), (2.0, "a little irregular"), (3.0, "irregular"), (math.inf, "very irregular"))
    assert DRIVE_LEVEL_WORDS == ((0.2, "barely any"), (0.5, "a little"), (0.8, "clear"), (math.inf, "strong"))
    assert INTERACTION_WORDS == ((60.0, "someone was with me just now"), (600.0, "it has been a little while since anyone was with me"), (math.inf, "it has been a long time since anyone was with me"))
    assert CERTAINTY_WORDS == ((0.4, "I doubt"), (0.7, "I think"), (0.9, "I believe"), (math.inf, "I am sure"))
    assert DRIVE_LEVEL_WORDS[2][0] == STRONG_DRIVE_BAND
    assert FATIGUE_DEFAULT_THRESHOLD == 100.0


def test_grade_documented_literals():
    assert grade(0.39, AROUSAL_WORDS) == "calm"
    assert grade(0.4, AROUSAL_WORDS) == "alert"
    assert grade(0.588, SURPRISE_WORDS) == "noticeably"
    assert grade(0.8, DRIVE_LEVEL_WORDS) == "strong"
    assert grade(0.0004, CHANGE_WORDS) == "barely changing"
    assert grade(0.6116, FAMILIARITY_WORDS) == "somewhat familiar"
    assert grade(-0.15, VALENCE_WORDS) == "neither good nor bad"


@pytest.mark.parametrize(
    "value",
    [None, True, False, "0.5", float("nan"), float("inf"), float("-inf")],
)
def test_grade_rejects_invalid_values(value):
    assert grade(value, CHANGE_WORDS) is None


def test_felt_templates_covers_all_keys():
    for key in TEMPLATES:
        assert key in FELT_TEMPLATES
    assert ("audition", "audition.perception") in FELT_TEMPLATES
    assert ("embodiment", "embodiment.chat") in FELT_TEMPLATES


@pytest.mark.parametrize(
    "source, type_, payload, expected",
    [
        (
            "vision",
            "vision.report",
            {
                "change_score": 0.0004,
                "habituation_score": 0.6116,
                "encoder_model_id": "dinov2-small",
                "normalised_error": 1.2,
            },
            "What I see is barely changing, feels somewhat familiar and is a little unexpected.",
        ),
        (
            "audition",
            "audition.perception",
            {
                "change_score": 0.12,
                "normalised_error": 3.4,
                "energy_dbfs": -30.5,
            },
            "What I hear is changing noticeably and is very unexpected.",
        ),
        (
            "interoception",
            "interoception.report",
            {
                "wellness": 0.82,
                "alerts": [],
                "prediction_error": 1.4437,
                "mean_prediction_error": 1.0,
                "fatigue_value": 4.7978,
                "fatigue_threshold": 100.0,
            },
            "My body feels well and is a little unexpected. I feel rested.",
        ),
        (
            "sequence",
            "sequence.report",
            {
                "anomaly_score": 2.5,
                "habituation_score": 0.2,
                "rumination_detected": False,
                "time_since_last_interaction_s": 900.0,
                "temporal_prediction_error": 0.31,
            },
            "The rhythm of things feels irregular and feels new to me. It has been a long time since anyone was with me.",
        ),
        (
            "affect",
            "affect.state",
            {
                "state": {"valence": 0.1, "arousal": 0.35, "dominance": 0.0},
                "drives": {"curiosity": 0.3, "boredom": 0.85},
                "emotion": "neutral",
            },
            "I feel calm, neither good nor bad and steady. I sense strong boredom and a little curiosity. My emotion is neutral.",
        ),
    ],
)
def test_felt_examples(source, type_, payload, expected):
    renderer = felt_renderer()
    assert renderer.render_event(_ev(source, type_, payload)) == expected


def test_language_own_words():
    renderer = felt_renderer()
    assert renderer.render_event(_ev("language", "external_speech", {"text": "I like the light"})) == 'I said: "I like the light".'
    assert renderer.render_event(_ev("language", "internal_speech", {"text": "it is quiet"})) == 'I thought: "it is quiet".'
    assert renderer.render_event(_ev("language", "external_speech", {"text": ""})) == "I spoke."
    assert renderer.render_event(_ev("language", "internal_speech", {"text": ""})) == "I had a thought."
    assert renderer.render_event(_ev("language", "external_speech", {"text": "surprise 0.588"})) == "I said something."
    assert renderer.render_event(_ev("language", "internal_speech", {"text": "surprise 0.588"})) == "I had a thought."


DIGIT_PAYLOAD = {
    "change_score": 0.123,
    "habituation_score": 0.123,
    "encoder_model_id": "dinov2-small",
    "normalised_error": 1.23,
    "energy_dbfs": -30.5,
    "wellness": 0.82,
    "alerts": [],
    "prediction_error": 1.4437,
    "mean_prediction_error": 1.0,
    "fatigue_value": 4.7978,
    "fatigue_threshold": 100.0,
    "value": 0.5,
    "threshold": 100.0,
    "crossed": True,
    "action": "policy_3",
    "reason": "the count is 3",
    "anomaly_score": 2.5,
    "rumination_detected": True,
    "time_since_last_interaction_s": 900.0,
    "temporal_prediction_error": 0.31,
    "state": {"arousal": 0.35, "valence": 0.1, "dominance": 0.0},
    "drives": {"curiosity": 0.3, "boredom": 0.85},
    "emotion": "neutral 7",
    "drive": "rest-3",
    "description": "mem-123",
    "text": "hello 42",
    "category": "agent 7",
    "statement": "the count is 3",
    "confidence": 0.95,
    "kind": "policy_3",
    "count": 3,
    "agent_label": "agent 7",
    "agent_id": "id-9",
    "familiarity": 0.95,
    "accepted": True,
    "success": True,
    "memory_id": "mem-123",
}

HEARD_SPEECH_KEYS = {("audition", "audition.transcription"), ("embodiment", "embodiment.chat")}
GUARDED_KEYS = [k for k in FELT_TEMPLATES if k not in HEARD_SPEECH_KEYS]


@pytest.mark.parametrize("key", GUARDED_KEYS)
def test_no_digits_digit_heavy_payload(key):
    source, type_ = key
    renderer = felt_renderer()
    line = renderer.render_event(_ev(source, type_, DIGIT_PAYLOAD))
    assert line
    assert not any(ch.isdigit() for ch in line)


@pytest.mark.parametrize("key", GUARDED_KEYS)
def test_no_digits_empty_payload(key):
    source, type_ = key
    renderer = felt_renderer()
    line = renderer.render_event(_ev(source, type_, {}))
    assert line
    assert not any(ch.isdigit() for ch in line)


def test_digit_guard_replaces_line_with_fallback():
    renderer = felt_renderer()
    line = renderer.render_event(
        _ev("planning", "planning.belief", {"statement": "the count is 3", "confidence": 0.95})
    )
    assert line == "Something stirs in my plans."


def test_heard_speech_keeps_digits():
    renderer = felt_renderer()
    line1 = renderer.render_event(_ev("audition", "audition.transcription", {"text": "call me at 5"}))
    assert line1 == 'Speech heard: "call me at 5".'
    line2 = renderer.render_event(_ev("embodiment", "embodiment.chat", {"text": "hello 42"}))
    assert line2 == 'Someone writes to me: "hello 42".'


def test_felt_fallback_unknown_keys():
    renderer = felt_renderer()
    assert renderer.render_event(_ev("zz9", "zz9.thing", {"x": 1.5})) == "Something stirs in me."
    assert renderer.render_event(_ev("vision", "vision.unknown_type", {"x": 1})) == "Something stirs in what I see."


def test_felt_event_phrase():
    assert felt_event_phrase("vision", 0.588) == "Something in what I see stands out noticeably."
    assert felt_event_phrase("audition", None) == "Something in what I hear draws my attention."
    assert felt_event_phrase("zz", 0.9) == "Something in me stands out sharply."


def test_felt_redaction():
    ev1 = _ev("audition", "audition.transcription", {"text": "secret 9"})
    assert redact_heard_speech_felt(ev1) == 'Speech heard: "[heard speech]".'
    ev2 = _ev("embodiment", "embodiment.chat", {"text": "hello 42"})
    assert redact_heard_speech_felt(ev2) == 'Someone writes to me: "[heard speech]".'
    ev3 = _ev("vision", "vision.report", {"change_score": 0.1})
    assert redact_heard_speech_felt(ev3) is None


def test_numeric_renderer_unchanged():
    renderer = FaithfulRenderer()
    vision = _ev(
        "vision",
        "vision.report",
        {
            "change_score": 0.0004,
            "habituation_score": 0.6116,
            "encoder_model_id": "dinov2-small",
            "normalised_error": 1.2,
        },
    )
    interoception = _ev(
        "interoception",
        "interoception.report",
        {
            "wellness": 0.82,
            "alerts": [],
            "prediction_error": 1.4437,
            "mean_prediction_error": 1.0,
            "fatigue_value": 4.7978,
            "fatigue_threshold": 100.0,
        },
    )
    sequence = _ev(
        "sequence",
        "sequence.report",
        {
            "anomaly_score": 2.5,
            "habituation_score": 0.2,
            "rumination_detected": False,
            "time_since_last_interaction_s": 900.0,
            "temporal_prediction_error": 0.31,
        },
    )
    affect = _ev(
        "affect",
        "affect.state",
        {
            "state": {"valence": 0.1, "arousal": 0.35, "dominance": 0.0},
            "drives": {"curiosity": 0.3, "boredom": 0.85},
            "emotion": "neutral",
        },
    )
    audition = _ev(
        "audition",
        "audition.perception",
        {
            "change_score": 0.12,
            "normalised_error": 3.4,
            "energy_dbfs": -30.5,
        },
    )
    embodiment = _ev("embodiment", "embodiment.chat", {"text": "hello 42"})

    assert renderer.render_event(vision) == (
        "Vision via dinov2-small reports change 0.0004, habituation 0.6116."
    )
    assert renderer.render_event(interoception) == (
        "Interoception reports wellness 0.82, no alerts, prediction error 1.4437, fatigue 4.7978."
    )
    assert renderer.render_event(sequence) == (
        "Sequence reports anomaly 2.5, habituation 0.2, 900 seconds since interaction, temporal prediction error 0.31."
    )
    assert renderer.render_event(affect) == (
        "Affect state: arousal 0.35, dominance 0, valence 0.1. Drives: boredom 0.85, curiosity 0.3. Emotion: neutral."
    )
    assert renderer.render_event(audition) == (
        "audition emitted audition.perception carrying change_score=0.12, energy_dbfs=-30.5, normalised_error=3.4."
    )
    assert renderer.render_event(embodiment) == (
        "embodiment emitted embodiment.chat carrying text=hello 42."
    )
    assert redact_heard_speech(embodiment) == (
        "embodiment emitted embodiment.chat carrying text=[heard speech]."
    )


def test_felt_snapshot():
    events = [
        ("e1", _ev(
            "vision",
            "vision.report",
            {
                "change_score": 0.0004,
                "habituation_score": 0.6116,
                "encoder_model_id": "dinov2-small",
                "normalised_error": 1.2,
            },
        )),
        ("e2", _ev(
            "audition",
            "audition.perception",
            {
                "change_score": 0.12,
                "normalised_error": 3.4,
                "energy_dbfs": -30.5,
            },
        )),
        ("e3", _ev(
            "interoception",
            "interoception.report",
            {
                "wellness": 0.82,
                "alerts": [],
                "prediction_error": 1.4437,
                "mean_prediction_error": 1.0,
                "fatigue_value": 4.7978,
                "fatigue_threshold": 100.0,
            },
        )),
        ("e4", _ev(
            "sequence",
            "sequence.report",
            {
                "anomaly_score": 2.5,
                "habituation_score": 0.2,
                "rumination_detected": False,
                "time_since_last_interaction_s": 900.0,
                "temporal_prediction_error": 0.31,
            },
        )),
        ("e5", _ev(
            "affect",
            "affect.state",
            {
                "state": {"valence": 0.1, "arousal": 0.35, "dominance": 0.0},
                "drives": {"curiosity": 0.3, "boredom": 0.85},
                "emotion": "neutral",
            },
        )),
    ]
    scores = {eid: 0.5 for eid, _ in events}
    snap = WorkspaceSnapshot(tick_index=1, selected_events=events, salience_scores=scores)
    renderer = felt_renderer()
    text = renderer.render_snapshot_bounded(snap, max_events=8, char_budget=2000)
    lines = text.split("\n")
    assert len(lines) == 5
    assert all(line.startswith("- ") for line in lines)
    assert not any(ch.isdigit() for ch in text)
