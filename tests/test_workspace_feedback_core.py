# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the workspace feedback integration in core.py and boot helpers."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kaine.boot.errors import ConfigurationError
from kaine.boot.feedback import (
    feedback_section,
    make_workspace_feedback,
)
from kaine.bus.schema import Event
from kaine.config import load_kaine_config
from kaine.workspace import (
    NoveltyTracker,
    RuleBasedSalience,
    StaticAffectModulator,
    StaticGoalScorer,
    Workspace,
)
from kaine.workspace.coherence import CoherenceScorer
from kaine.workspace.feedback import FeedbackController, WorkspaceFeedbackSettings

FIXED_TS = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _strategy():
    return RuleBasedSalience(
        novelty=NoveltyTracker(window=32),
        goal_scorer=StaticGoalScorer(),
        affect_modulator=StaticAffectModulator(),
    )


def _event(source: str, type: str, payload: dict, salience: float = 0.5) -> Event:
    return Event(
        source=source,
        type=type,
        payload=payload,
        salience=salience,
        timestamp=FIXED_TS,
    )


def _report_event(source: str, error_ratio: float, disagreement: float, salience: float = 0.9):
    return _event(
        source,
        f"{source}.report",
        {
            "workspace_feedback": {
                "error_ratio": error_ratio,
                "disagreement": disagreement,
                "gain": 1.0,
            }
        },
        salience,
    )


def _sequence_event(vector=None):
    if vector is None:
        vector = [0.1] * 24
    return _event("sequence", "sequence.report", {"predicted_next_feature_vector": vector}, 0.5)


@pytest.mark.asyncio
async def test_feedback_off_bit_for_bit():
    s1 = _strategy()
    s2 = _strategy()
    workspace_off = Workspace(s1)
    workspace_none = Workspace(s2, feedback=None)

    ticks = [
        (
            [
                ("vision.out:1-0", _report_event("vision", 2.5, 3.0)),
                ("audition.out:1-0", _report_event("audition", 0.5, 0.0)),
            ],
            {"tick_index": 0, "is_experiential": False},
        ),
        (
            [
                ("vision.out:1-1", _report_event("vision", 2.5, 3.0)),
                ("audition.out:1-1", _report_event("audition", 0.5, 0.0)),
                ("sequence.out:1-1", _sequence_event()),
            ],
            {"tick_index": 1, "is_experiential": True},
        ),
        ([], {"tick_index": 2, "is_experiential": True}),
    ]

    for events, context in ticks:
        snap_off = await workspace_off.select(events, context)
        snap_none = await workspace_none.select(events, context)

        assert snap_off.selected_events == snap_none.selected_events
        assert snap_off.inhibited == snap_none.inhibited
        assert snap_off.salience_scores == snap_none.salience_scores
        assert snap_off.metadata == snap_none.metadata

        assert "workspace_feedback" not in snap_off.metadata
        assert "workspace_feedback" not in snap_none.metadata


@pytest.mark.asyncio
async def test_feedback_full_broadcast_in_metadata():
    settings = WorkspaceFeedbackSettings.from_section({"enabled": True, "arm": "full"})
    controller = FeedbackController(settings, clock=lambda: 0.0)
    workspace = Workspace(_strategy(), feedback=controller)
    workspace_off = Workspace(_strategy())

    events = [
        ("vision.out:1-0", _report_event("vision", 2.5, 3.0)),
        (
            "audition.out:1-0",
            _event(
                "audition",
                "audition.perception",
                {"workspace_feedback": {"error_ratio": 0.5, "disagreement": 0.0, "gain": 1.0}},
                0.9,
            ),
        ),
        ("sequence.out:1-0", _sequence_event()),
    ]
    context = {"tick_index": 0, "is_experiential": True}

    snap = await workspace.select(events, context)
    snap_off = await workspace_off.select(events, context)

    assert [eid for eid, _ in snap.selected_events] == [
        eid for eid, _ in snap_off.selected_events
    ]
    assert snap.salience_scores == snap_off.salience_scores

    fb = snap.metadata["workspace_feedback"]
    assert fb["arm"] == "full"
    assert fb["gains"]["audition"] == pytest.approx(1.1, abs=0.01)
    assert fb["gains"]["vision"] == pytest.approx(0.9, abs=0.01)
    assert fb["sequence_prediction"] == [0.1] * 24


@pytest.mark.asyncio
async def test_feedback_non_broadcast_observes_but_does_not_publish():
    settings = WorkspaceFeedbackSettings.from_section({"enabled": True, "arm": "full"})
    controller = FeedbackController(settings, clock=lambda: 0.0)
    workspace = Workspace(_strategy(), feedback=controller)

    non_broadcast = await workspace.select(
        [("sequence.out:1-0", _sequence_event())],
        {"tick_index": 0, "is_experiential": False},
    )
    assert "workspace_feedback" not in non_broadcast.metadata
    assert controller.gains == {"vision": 1.0, "audition": 1.0, "interoception": 1.0}

    broadcast = await workspace.select(
        [("vision.out:1-1", _report_event("vision", 0.5, 0.0))],
        {"tick_index": 1, "is_experiential": True},
    )
    fb = broadcast.metadata["workspace_feedback"]
    assert fb["sequence_prediction"] == [0.1] * 24


@pytest.mark.asyncio
async def test_feedback_inhibited_broadcast_has_no_feedback_key():
    settings = WorkspaceFeedbackSettings.from_section({"enabled": True, "arm": "full"})
    controller = FeedbackController(settings, clock=lambda: 0.0)
    workspace = Workspace(_strategy(), feedback=controller)

    events = [("vision.out:1-0", _report_event("vision", 2.5, 3.0, salience=0.05))]
    snap = await workspace.select(events, {"tick_index": 0, "is_experiential": True})

    assert snap.inhibited is True
    assert "workspace_feedback" not in snap.metadata


def test_feedback_constructor_refusals():
    settings = WorkspaceFeedbackSettings.from_section({"enabled": True, "arm": "full"})
    controller = FeedbackController(settings, clock=lambda: 0.0)

    with pytest.raises(ValueError, match="workspace feedback runs on the competitive arm"):
        Workspace(_strategy(), arm="matched", arm_seed=1, feedback=controller)

    with pytest.raises(ValueError, match="workspace feedback runs with the coherence layer off"):
        Workspace(
            _strategy(),
            coherence=CoherenceScorer(
                plv_window=10,
                coherence_floor=0.8,
                coherence_ceiling=1.25,
            ),
            feedback=controller,
        )


def test_feedback_boot_helpers():
    assert make_workspace_feedback({}, seed=1) is None
    assert make_workspace_feedback({"workspace": {"feedback": {"enabled": False}}}, seed=1) is None

    controller = make_workspace_feedback(
        {"workspace": {"feedback": {"enabled": True, "arm": "full"}}},
        seed=1,
    )
    assert isinstance(controller, FeedbackController)
    assert controller.arm == "full"

    with pytest.raises(ConfigurationError, match="workspace feedback runs with the coherence layer off"):
        make_workspace_feedback(
            {"oscillator": {"enabled": True}, "workspace": {"feedback": {"enabled": True, "arm": "full"}}},
            seed=1,
        )

    with pytest.raises(ConfigurationError, match="workspace feedback runs on the competitive arm"):
        make_workspace_feedback(
            {"workspace": {"arm": "pooled", "feedback": {"enabled": True, "arm": "full"}}},
            seed=1,
        )

    with pytest.raises(ConfigurationError, match="workspace feedback runs with the positive control off"):
        make_workspace_feedback(
            {"positive_control": {"enabled": True}, "workspace": {"feedback": {"enabled": True, "arm": "full"}}},
            seed=1,
        )

    with pytest.raises(ConfigurationError, match="matched_random feedback arm needs the run seed"):
        make_workspace_feedback(
            {"workspace": {"feedback": {"enabled": True, "arm": "matched_random"}}},
            seed=None,
        )

    with pytest.raises(ConfigurationError, match="unknown key"):
        make_workspace_feedback(
            {"workspace": {"feedback": {"enabled": True, "arm": "full", "bad_key": 1}}},
            seed=1,
        )

    with pytest.raises(ConfigurationError, match="must be a table"):
        feedback_section({"workspace": {"feedback": 3}})


def test_feedback_shipped_config_is_off():
    cfg = load_kaine_config(
        profile="first_configuration",
        operator_path="/nonexistent-operator-for-tests.toml",
    )
    assert make_workspace_feedback(cfg, seed=1) is None
