# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

from fractions import Fraction

import pytest

from kaine.experiment.tone_analysis import (
    ToneAnalysisError,
    ToneEvent,
    accessed_fractions,
    adjusted_statistic,
    bin_index,
    run_statistic,
    tone_events,
    tone_runs_still_needed,
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
        entry_id = f"audition.out:{i}-0"
        accessed = i in accessed_set
        records.append(
            {
                "event_type": "audition.emotion",
                "source": "audition",
                "entry_id": entry_id,
                "category": "happy" if emotional else "neutral",
                "classified": True,
                "tone_rule": "error_ratio",
                "tone_error_ratio": 0.5 + 0.01 * i,
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
            "salience_scores": {"audition.out:0-0": 0.9},
            "entries": [
                {
                    "entry_id": "audition.out:0-0",
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


def test_duplicate_entry_ids_in_one_broadcast_raise():
    records = _run(1, 1, 0, 0)
    records[1]["entries"].append(
        {
            "entry_id": "audition.out:0-0",
            "source": "topos",
            "type": "topos.report",
            "salience": 0.5,
        }
    )
    with pytest.raises(ToneAnalysisError):
        tone_events(records)


def test_bin_index_respects_right_edges():
    edges = [1.0, 2.0, 3.0, 4.0]
    assert bin_index(0.5, edges) == 0
    assert bin_index(1.0, edges) == 1
    assert bin_index(4.5, edges) == 4


def test_adjusted_statistic_averages_within_bins():
    edges = [1.0, 2.0, 3.0, 4.0]

    def make(error, emotional, accessed):
        return ToneEvent(
            entry_id=f"{error}-{emotional}-{accessed}",
            emotional=emotional,
            error_ratio=error,
            accessed=accessed,
        )

    # Bin 0: emotional accessed (1), emotional not accessed (1), neutral not
    # accessed (2). Emotional fraction 0.5, neutral fraction 0.0, difference 0.5.
    bin0 = [
        make(0.5, True, True),
        make(0.5, True, False),
        make(0.5, False, False),
        make(0.5, False, False),
    ]
    # Bin 2: emotional accessed (1), neutral accessed (1). Both fractions 1.0.
    bin2 = [make(2.5, True, True), make(2.5, False, True)]
    # Bin 4: only neutral events, so no within-bin difference.
    bin4 = [make(4.5, False, True), make(4.5, False, False)]
    events = bin0 + bin2 + bin4
    assert adjusted_statistic(events, edges) == pytest.approx(0.25)


def test_adjusted_statistic_none_when_every_bin_has_one_class():
    edges = [1.0, 2.0, 3.0, 4.0]
    events = [
        ToneEvent(entry_id="e1", emotional=True, error_ratio=0.5, accessed=True),
        ToneEvent(entry_id="n1", emotional=False, error_ratio=2.5, accessed=True),
    ]
    assert adjusted_statistic(events, edges) is None


def test_tone_runs_still_needed_counts_defined_differences():
    assert tone_runs_still_needed([0.1] * 100 + [None] * 5) == 2
    assert tone_runs_still_needed([0.1] * 102) == 0


def test_bare_tone_event_id_is_refused():
    records = _run(1, 1, 0, 0)
    records[0]["entry_id"] = "0-0"
    with pytest.raises(ToneAnalysisError):
        tone_events(records)


def test_bare_member_id_is_refused():
    records = _run(1, 1, 0, 0)
    records[1]["entries"][0]["entry_id"] = "0-0"
    with pytest.raises(ToneAnalysisError):
        tone_events(records)
