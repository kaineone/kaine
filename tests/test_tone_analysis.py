# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

from fractions import Fraction

import pytest

from kaine.experiment.tone_analysis import (
    ToneAnalysisError,
    accessed_fractions,
    run_statistic,
    tone_events,
    tone_verdict,
)
from kaine.experiment.verdict import Outcome


def _run(n_emotional, accessed_emotional, n_neutral, accessed_neutral):
    records = []
    total = n_emotional + n_neutral
    accessed_emotional_set = set(range(accessed_emotional))
    accessed_neutral_set = set(
        range(n_emotional, n_emotional + accessed_neutral)
    )
    accessed_set = accessed_emotional_set | accessed_neutral_set

    for i in range(total):
        emotional = i < n_emotional
        entry_id = f"{i}-0"
        accessed = i in accessed_set
        records.append(
            {
                "event_type": "audition.emotion",
                "source": "audition",
                "entry_id": entry_id,
                "category": "happy" if emotional else "neutral",
                "classified": True,
                "tone_rule": "error_ratio",
                "normalised_error": 0.5 + 0.01 * i,
            }
        )
        records.append(
            {
                "event_type": "workspace.broadcast",
                "inhibited": False,
                "access_threshold": 0.35,
                "salience_scores": {entry_id: 0.6 if accessed else 0.2},
                "entries": [
                    {
                        "entry_id": entry_id,
                        "source": "audition",
                        "type": "audition.emotion",
                        "salience": 0.5,
                    }
                ],
            }
        )
    return records


def test_tone_fractions_and_statistic():
    records = _run(10, 6, 10, 2)
    events = tone_events(records)
    assert len(events) == 20
    emotional, neutral = accessed_fractions(events)
    assert emotional == pytest.approx(0.6)
    assert neutral == pytest.approx(0.2)
    assert run_statistic(events) == pytest.approx(0.4)


def test_inhibited_broadcast_does_not_access():
    records = _run(1, 0, 0, 0)
    records[1]["inhibited"] = True
    records[1]["salience_scores"] = {"0-0": 0.9}
    events = tone_events(records)
    assert events[0].accessed is False


def test_join_is_on_source_type_id():
    records = _run(1, 0, 0, 0)
    records.append(
        {
            "event_type": "workspace.broadcast",
            "inhibited": False,
            "access_threshold": 0.35,
            "salience_scores": {"0-0": 0.9},
            "entries": [
                {
                    "entry_id": "0-0",
                    "source": "other",
                    "type": "audition.emotion",
                    "salience": 0.5,
                }
            ],
        }
    )
    events = tone_events(records)
    assert events[0].accessed is False


def test_classified_and_rule_and_member_validation():
    records = _run(1, 0, 0, 0)
    records[0]["classified"] = False
    assert tone_events(records) == []

    records = _run(1, 0, 0, 0)
    del records[0]["classified"]
    with pytest.raises(ToneAnalysisError):
        tone_events(records)

    records = _run(1, 0, 0, 0)
    records[0]["tone_rule"] = "categorical"
    with pytest.raises(ToneAnalysisError):
        tone_events(records)

    records = _run(1, 0, 0, 0)
    records[1]["entries"][0].pop("entry_id")
    with pytest.raises(ToneAnalysisError):
        tone_events(records)


def test_only_emotional_statistic_is_none():
    records = _run(5, 2, 0, 0)
    events = tone_events(records)
    assert run_statistic(events) is None


def test_tone_verdicts():
    result = tone_verdict([0.4] * 10, 0.1)
    assert result.outcome == Outcome.WIN
    assert result.p_win == Fraction(1, 1024)

    result = tone_verdict([-0.4] * 10, 0.1)
    assert result.outcome == Outcome.NEGATIVE
    assert result.p_negative == Fraction(1, 1024)

    result = tone_verdict([None] * 10, 0.1)
    assert result.outcome == Outcome.NOT_EXERCISED
    assert result.p_win == Fraction(1)
    assert result.p_negative == Fraction(1)

    result = tone_verdict([0.4] * 5 + [-0.4] * 5, 0.1)
    assert result.outcome == Outcome.NULL

    result = tone_verdict([0.1] * 5, 0.1)
    assert result.outcome == Outcome.NULL
    assert result.p_win == Fraction(1)


def test_broadcast_without_threshold_raises():
    records = _run(1, 1, 0, 0)
    del records[1]["access_threshold"]
    with pytest.raises(ToneAnalysisError):
        tone_events(records)
