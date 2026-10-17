# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the workspace feedback controller."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.workspace.feedback import (
    FEEDBACK_KEY,
    PROCESSORS,
    REPORT_TYPES,
    SEQUENCE_PREDICTION_DIM,
    SEQUENCE_PREDICTION_KEY,
    SEQUENCE_REPORT_TYPE,
    SEQUENCE_SOURCE,
    FeedbackController,
    FeedbackSettingsError,
    WorkspaceFeedbackSettings,
)


def _report(source, *, ratio=None, disagreement=None, gain=1.0, eid=None, salience=0.6):
    payload = {
        FEEDBACK_KEY: {
            "error_ratio": ratio,
            "disagreement": disagreement,
            "gain": gain,
        }
    }
    return (
        eid or f"{source}:1",
        Event(
            source=source,
            type=REPORT_TYPES[source],
            payload=payload,
            salience=salience,
            timestamp=datetime.now(timezone.utc),
        ),
    )


def _snapshot(events, *, scores=None, threshold=0.35, inhibited=False):
    scores = dict(scores) if scores else {}
    for eid, _ in events:
        scores.setdefault(eid, 0.6)
    return WorkspaceSnapshot(
        tick_index=0,
        selected_events=events,
        inhibited=inhibited,
        salience_scores=scores,
        metadata={"access_threshold": threshold},
    )


def test_settings_from_section():
    assert WorkspaceFeedbackSettings.from_section(None) is None
    assert WorkspaceFeedbackSettings.from_section({}) is None
    assert WorkspaceFeedbackSettings.from_section({"enabled": False, "arm": "full"}) is None
    assert WorkspaceFeedbackSettings.from_section({"enabled": True, "arm": "off"}) is None

    full = WorkspaceFeedbackSettings.from_section({"enabled": True})
    assert full is not None
    assert full.arm == "full"
    assert full.pi_min == pytest.approx(0.8)
    assert full.pi_max == pytest.approx(1.25)
    assert full.disagreement_threshold == pytest.approx(2.0)
    assert full.conflict_error_ratio == pytest.approx(2.0)
    assert full.gain_step == pytest.approx(0.1)
    assert full.gain_relax_s == pytest.approx(10.0)
    assert full.refractory_s == pytest.approx(10.0)
    assert full.head_learning_rate == pytest.approx(1e-3)
    assert full.head_active
    assert full.gain_active
    assert full.conflict_active

    head_only = WorkspaceFeedbackSettings.from_section(
        {"enabled": True, "arm": " Head_Only "}
    )
    assert head_only.arm == "head_only"
    assert not head_only.gain_active
    assert not head_only.conflict_active

    head_gain = WorkspaceFeedbackSettings.from_section({"enabled": True, "arm": "head_gain"})
    assert head_gain.gain_active
    assert not head_gain.conflict_active

    matched = WorkspaceFeedbackSettings.from_section({"enabled": True, "arm": "matched_random"})
    assert matched.gain_active
    assert matched.conflict_active

    with pytest.raises(FeedbackSettingsError):
        WorkspaceFeedbackSettings.from_section({"enabled": False, "unknown_key": 1})
    with pytest.raises(FeedbackSettingsError):
        WorkspaceFeedbackSettings.from_section({"enabled": False, "arm": "bad_arm"})
    with pytest.raises(FeedbackSettingsError):
        WorkspaceFeedbackSettings.from_section({"enabled": 1, "arm": "full"})
    with pytest.raises(FeedbackSettingsError):
        WorkspaceFeedbackSettings.from_section({"enabled": True, "pi_min": 1.1})
    with pytest.raises(FeedbackSettingsError):
        WorkspaceFeedbackSettings.from_section({"enabled": True, "pi_max": 0.9})
    with pytest.raises(FeedbackSettingsError):
        WorkspaceFeedbackSettings.from_section({"enabled": True, "gain_step": 0})
    with pytest.raises(FeedbackSettingsError):
        WorkspaceFeedbackSettings.from_section(
            {"enabled": True, "disagreement_threshold": float("nan")}
        )

    zero_refractory = WorkspaceFeedbackSettings.from_section(
        {"enabled": True, "refractory_s": 0}
    )
    assert zero_refractory is not None
    assert zero_refractory.refractory_s == pytest.approx(0.0)


def test_matched_random_requires_seed():
    settings = WorkspaceFeedbackSettings.from_section(
        {"enabled": True, "arm": "matched_random"}
    )
    with pytest.raises(ValueError, match="matched_random feedback arm needs a seed"):
        FeedbackController(settings)


def test_full_conflict_moves_gain_toward_lowest_pwe():
    settings = WorkspaceFeedbackSettings.from_section(
        {
            "enabled": True,
            "arm": "full",
            "gain_relax_s": 1e9,
            "refractory_s": 10.0,
        }
    )
    ctrl = FeedbackController(settings, clock=lambda: 0.0)
    vis = _report("vision", ratio=2.5, disagreement=3.0)
    aud = _report("audition", ratio=0.5)
    snap = _snapshot([vis, aud])

    meta = ctrl.on_broadcast(snap, now=0.0)
    assert meta is not None
    assert meta["gains"] == pytest.approx(
        {"vision": 0.9, "audition": 1.1, "interoception": 1.0}
    )
    assert ctrl.gains == pytest.approx(meta["gains"])

    assert len(meta["episodes"]) == 1
    ep = meta["episodes"][0]
    assert ep["kind"] == "conflict"
    assert ep["conflicting"] == "vision"
    assert ep["toward"] == "audition"
    assert ep["away"] == "vision"
    assert ep["delta"] == pytest.approx(0.1)


def test_refractory_prevents_immediate_repeat():
    settings = WorkspaceFeedbackSettings.from_section(
        {
            "enabled": True,
            "arm": "full",
            "gain_relax_s": 1e9,
            "refractory_s": 10.0,
        }
    )
    ctrl = FeedbackController(settings, clock=lambda: 0.0)
    vis = _report("vision", ratio=2.5, disagreement=3.0)
    aud = _report("audition", ratio=0.5)
    snap = _snapshot([vis, aud])

    meta0 = ctrl.on_broadcast(snap, now=0.0)
    assert len(meta0["episodes"]) == 1

    meta1 = ctrl.on_broadcast(snap, now=1.0)
    assert meta1["episodes"] == []
    assert meta1["gains"] == pytest.approx(meta0["gains"], abs=1e-9)

    meta2 = ctrl.on_broadcast(snap, now=20.0)
    assert len(meta2["episodes"]) == 1
    assert meta2["gains"] == pytest.approx(
        {"vision": 0.8, "audition": 1.2, "interoception": 1.0}, abs=1e-6
    )


def test_bounds_and_mean_preserved_over_repeated_conflicts():
    settings = WorkspaceFeedbackSettings.from_section(
        {
            "enabled": True,
            "arm": "full",
            "gain_relax_s": 1e9,
            "refractory_s": 10.0,
        }
    )
    ctrl = FeedbackController(settings, clock=lambda: 0.0)
    vis = _report("vision", ratio=10.0, disagreement=5.0)
    aud = _report("audition", ratio=0.1)
    inter = _report("interoception", ratio=1.0)
    snap = _snapshot([vis, aud, inter])

    for t in range(0, 5000, 100):
        ctrl.on_broadcast(snap, now=float(t))
        for processor in PROCESSORS:
            assert settings.pi_min <= ctrl.gains[processor] <= settings.pi_max
        mean = sum(ctrl.gains.values()) / len(PROCESSORS)
        assert mean == pytest.approx(1.0, abs=1e-12)


def test_relaxation_pulls_gains_toward_one():
    settings = WorkspaceFeedbackSettings.from_section(
        {
            "enabled": True,
            "arm": "full",
            "gain_relax_s": 10.0,
            "refractory_s": 10.0,
        }
    )
    ctrl = FeedbackController(settings, clock=lambda: 0.0)
    vis = _report("vision", ratio=10.0, disagreement=5.0)
    aud = _report("audition", ratio=0.1)
    snap = _snapshot([vis, aud])

    ctrl.on_broadcast(snap, now=0.0)
    ctrl.relax(100.0)
    for processor in PROCESSORS:
        assert ctrl.gains[processor] == pytest.approx(1.0, abs=1e-3)
    mean = sum(ctrl.gains.values()) / len(PROCESSORS)
    assert mean == pytest.approx(1.0, abs=1e-15)

    # A timestamp earlier than the last one leaves state unchanged.
    ctrl._last_time = 200.0
    gains_before = dict(ctrl.gains)
    ctrl.relax(100.0)
    assert ctrl._last_time == 200.0
    assert ctrl.gains == pytest.approx(gains_before, abs=1e-15)


def test_inhibited_broadcast_returns_none():
    settings = WorkspaceFeedbackSettings.from_section(
        {"enabled": True, "arm": "full", "gain_relax_s": 1e9, "refractory_s": 10.0}
    )
    ctrl = FeedbackController(settings, clock=lambda: 0.0)
    vis = _report("vision", ratio=10.0, disagreement=5.0)
    aud = _report("audition", ratio=0.1)
    snap = _snapshot([vis, aud], inhibited=True)

    assert ctrl.on_broadcast(snap, now=0.0) is None
    assert ctrl.gains == pytest.approx(
        {"vision": 1.0, "audition": 1.0, "interoception": 1.0}
    )


def test_below_threshold_not_accessed():
    settings = WorkspaceFeedbackSettings.from_section(
        {"enabled": True, "arm": "full", "gain_relax_s": 1e9, "refractory_s": 10.0}
    )
    ctrl = FeedbackController(settings, clock=lambda: 0.0)
    vis = _report("vision", ratio=10.0, disagreement=5.0, salience=0.2)
    aud = _report("audition", ratio=0.1, salience=0.6)
    snap = _snapshot([vis, aud], scores={vis[0]: 0.2, aud[0]: 0.6})

    meta = ctrl.on_broadcast(snap, now=0.0)
    assert meta["episodes"] == []
    assert ctrl.gains == pytest.approx(
        {"vision": 1.0, "audition": 1.0, "interoception": 1.0}
    )


def test_single_accessed_conflicting_no_move_and_refractory():
    settings = WorkspaceFeedbackSettings.from_section(
        {"enabled": True, "arm": "full", "gain_relax_s": 1e9, "refractory_s": 10.0}
    )
    ctrl = FeedbackController(settings, clock=lambda: 0.0)
    vis = _report("vision", ratio=10.0, disagreement=5.0)
    snap = _snapshot([vis])

    meta0 = ctrl.on_broadcast(snap, now=0.0)
    assert meta0["episodes"] == [
        {
            "kind": "conflict",
            "conflicting": "vision",
            "toward": None,
            "away": None,
            "delta": 0.0,
        }
    ]
    assert ctrl.gains == pytest.approx(
        {"vision": 1.0, "audition": 1.0, "interoception": 1.0}
    )

    meta1 = ctrl.on_broadcast(snap, now=1.0)
    assert meta1["episodes"] == []


def test_head_only_and_head_gain_arms():
    # head_only: metadata is broadcast, but gains stay at one.
    settings = WorkspaceFeedbackSettings.from_section(
        {"enabled": True, "arm": "head_only"}
    )
    ctrl = FeedbackController(settings, clock=lambda: 0.0)
    vis = _report("vision", ratio=10.0, disagreement=5.0)
    aud = _report("audition", ratio=0.1)
    snap = _snapshot([vis, aud])

    meta = ctrl.on_broadcast(snap, now=0.0)
    assert meta["episodes"] == []
    assert meta["gains"] == pytest.approx(
        {"vision": 1.0, "audition": 1.0, "interoception": 1.0}
    )

    # head_gain: precision competition between eligible processors.
    settings = WorkspaceFeedbackSettings.from_section(
        {
            "enabled": True,
            "arm": "head_gain",
            "gain_relax_s": 1e9,
            "refractory_s": 10.0,
        }
    )
    ctrl = FeedbackController(settings, clock=lambda: 0.0)
    meta = ctrl.on_broadcast(snap, now=0.0)
    assert len(meta["episodes"]) == 1
    ep = meta["episodes"][0]
    assert ep["kind"] == "precision"
    assert ep["toward"] == "audition"
    assert ep["away"] == "vision"
    assert meta["gains"] == pytest.approx(
        {"vision": 0.9, "audition": 1.1, "interoception": 1.0}
    )

    # With only one eligible processor, head_gain does nothing.
    snap_single = _snapshot([vis])
    meta_single = ctrl.on_broadcast(snap_single, now=1.0)
    assert meta_single["episodes"] == []


def test_matched_random_reproducible_and_sees_only_seen_processors():
    settings = WorkspaceFeedbackSettings.from_section(
        {
            "enabled": True,
            "arm": "matched_random",
            "gain_relax_s": 1e9,
            "refractory_s": 10.0,
        }
    )
    a = FeedbackController(settings, seed=42, clock=lambda: 0.0)
    b = FeedbackController(settings, seed=42, clock=lambda: 0.0)

    vis = _report("vision", ratio=10.0, disagreement=5.0)
    aud = _report("audition", ratio=0.1)
    a.observe_candidates([vis, aud])
    b.observe_candidates([vis, aud])
    snap = _snapshot([vis, aud])

    for t in (0.0, 100.0, 200.0):
        meta_a = a.on_broadcast(snap, now=t)
        meta_b = b.on_broadcast(snap, now=t)
        assert meta_a["episodes"] == meta_b["episodes"]
        assert a.gains == pytest.approx(b.gains)
        for ep in meta_a["episodes"]:
            assert ep["kind"] == "random"
            assert ep["toward"] != ep["away"]

    assert a.gains["interoception"] == pytest.approx(1.0)
    assert b.gains["interoception"] == pytest.approx(1.0)

    # Single accessed conflicting processor: same no-move behavior as full.
    snap_single = _snapshot([vis])
    meta_single = a.on_broadcast(snap_single, now=300.0)
    assert meta_single["episodes"] == [
        {
            "kind": "conflict",
            "conflicting": "vision",
            "toward": None,
            "away": None,
            "delta": 0.0,
        }
    ]


def test_observe_candidates_sequence_prediction_and_seen_processors():
    settings = WorkspaceFeedbackSettings.from_section(
        {"enabled": True, "arm": "head_only"}
    )
    ctrl = FeedbackController(settings, clock=lambda: 0.0)

    valid = [float(i) for i in range(SEQUENCE_PREDICTION_DIM)]
    invalid_len = [0.0] * (SEQUENCE_PREDICTION_DIM - 1)
    invalid_nan = [0.0] * SEQUENCE_PREDICTION_DIM
    invalid_nan[0] = float("nan")
    invalid_bool = [0.0] * SEQUENCE_PREDICTION_DIM
    invalid_bool[0] = True

    def seq_event(prediction):
        return (
            "seq:1",
            Event(
                source=SEQUENCE_SOURCE,
                type=SEQUENCE_REPORT_TYPE,
                payload={SEQUENCE_PREDICTION_KEY: prediction},
                salience=0.5,
                timestamp=datetime.now(timezone.utc),
            ),
        )

    ctrl.observe_candidates([seq_event(valid)])
    assert ctrl.sequence_prediction == tuple(valid)

    ctrl.observe_candidates(
        [seq_event(invalid_len), seq_event(invalid_nan), seq_event(invalid_bool)]
    )
    assert ctrl.sequence_prediction == tuple(valid)

    later = [float(i + 10) for i in range(SEQUENCE_PREDICTION_DIM)]
    ctrl.observe_candidates([seq_event(later)])
    assert ctrl.sequence_prediction == tuple(later)

    meta = ctrl.on_broadcast(
        WorkspaceSnapshot(tick_index=0, selected_events=[], inhibited=False),
        now=0.0,
    )
    assert meta["sequence_prediction"] == later

    # matched_random samples only from processors it has seen.
    matched_settings = WorkspaceFeedbackSettings.from_section(
        {
            "enabled": True,
            "arm": "matched_random",
            "gain_relax_s": 1e9,
            "refractory_s": 0.0,
        }
    )
    m = FeedbackController(matched_settings, seed=7, clock=lambda: 0.0)
    vis = _report("vision", ratio=10.0, disagreement=5.0)
    aud = _report("audition", ratio=0.1)
    m.observe_candidates([vis, aud])
    m.on_broadcast(_snapshot([vis, aud]), now=0.0)
    assert m.gains["interoception"] == pytest.approx(1.0)


def test_report_without_feedback_dict_is_ineligible():
    settings = WorkspaceFeedbackSettings.from_section(
        {"enabled": True, "arm": "full", "gain_relax_s": 1e9, "refractory_s": 10.0}
    )
    ctrl = FeedbackController(settings, clock=lambda: 0.0)
    event = (
        "vision:1",
        Event(
            source="vision",
            type=REPORT_TYPES["vision"],
            payload={"something_else": 123},
            salience=0.6,
            timestamp=datetime.now(timezone.utc),
        ),
    )
    snap = _snapshot([event])

    meta = ctrl.on_broadcast(snap, now=0.0)
    assert meta["episodes"] == []
    assert ctrl.gains == pytest.approx(
        {"vision": 1.0, "audition": 1.0, "interoception": 1.0}
    )
