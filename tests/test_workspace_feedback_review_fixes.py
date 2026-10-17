# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for workspace feedback review fixes."""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone

import pytest

from kaine.boot.factories.sequence import make_sequence
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.feedback import TopDownBlend
from kaine.workspace.feedback import REPORT_TYPES, FeedbackController, WorkspaceFeedbackSettings


def _bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    return AsyncBus(BusConfig(password="x", audit_required=False), client=client)


def test_workspace_feedback_warning_without_forward_prediction(caplog):
    caplog.set_level(logging.WARNING, logger="kaine.boot.factories.sequence")
    bus = _bus()
    make_sequence(bus, {"workspace_feedback": {"enabled": True, "arm": "full"}})
    warnings = [
        r for r in caplog.records if r.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    assert warnings[0].message == (
        "workspace feedback is on but [sequence].forward_prediction is off; "
        "the top-down heads receive no sequence prediction"
    )


def test_workspace_feedback_no_warning_with_forward_prediction(caplog):
    caplog.set_level(logging.WARNING, logger="kaine.boot.factories.sequence")
    bus = _bus()
    make_sequence(
        bus,
        {
            "workspace_feedback": {"enabled": True, "arm": "full"},
            "forward_prediction": True,
        },
    )
    warnings = [
        r for r in caplog.records if r.levelno == logging.WARNING
    ]
    assert not warnings


def test_workspace_feedback_no_warning_when_feedback_off(caplog):
    caplog.set_level(logging.WARNING, logger="kaine.boot.factories.sequence")
    bus = _bus()
    make_sequence(bus, {"forward_prediction": False})
    warnings = [
        r for r in caplog.records if r.levelno == logging.WARNING
    ]
    assert not warnings


def _report(source, *, ratio, disagreement=None, gain=1.0, eid=None, salience=0.6):
    eid = eid or f"{source}:1"
    payload = {
        "workspace_feedback": {
            "error_ratio": ratio,
            "disagreement": disagreement,
            "gain": gain,
        }
    }
    event = Event(
        source=source,
        type=REPORT_TYPES[source],
        payload=payload,
        salience=salience,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    return eid, event


def _snapshot(reports, *, score=0.6, inhibited=False):
    selected_events = list(reports)
    salience_scores = {eid: score for eid, _ in reports}
    return WorkspaceSnapshot(
        tick_index=0,
        selected_events=selected_events,
        inhibited=inhibited,
        salience_scores=salience_scores,
        metadata={"access_threshold": 0.35},
    )


def test_head_gain_refractory_interval():
    settings = WorkspaceFeedbackSettings.from_section(
        {
            "enabled": True,
            "arm": "head_gain",
            "refractory_s": 10.0,
            "gain_relax_s": 1e9,
        }
    )
    controller = FeedbackController(settings)
    reports = [
        _report("vision", ratio=3.0),
        _report("audition", ratio=0.5),
    ]
    snapshot = _snapshot(reports)

    meta = controller.on_broadcast(snapshot, now=0.0)
    assert meta["gains"] == pytest.approx(
        {"vision": 0.9, "audition": 1.1, "interoception": 1.0}, abs=1e-6
    )
    assert len(meta["episodes"]) == 1
    assert meta["episodes"][0]["kind"] == "precision"

    meta = controller.on_broadcast(snapshot, now=5.0)
    assert meta["gains"] == pytest.approx(
        {"vision": 0.9, "audition": 1.1, "interoception": 1.0}, abs=1e-6
    )
    assert not meta["episodes"]

    meta = controller.on_broadcast(snapshot, now=20.0)
    assert meta["gains"] == pytest.approx(
        {"vision": 0.8, "audition": 1.2, "interoception": 1.0}, abs=1e-6
    )
    assert len(meta["episodes"]) == 1
    assert meta["episodes"][0]["kind"] == "precision"


class FakeInner:
    def __init__(self):
        self._last_prediction = None
        self._last_null_prediction = None
        self.last_null_error = None
        self.last_scored_had_context = False
        self.last_error_defined = True
        self.last_reading_skipped = False
        self._after_skip = False
        self.suspended = False
        self.context_dim = 24

    def step(self, feature, context=None, null_context=None):
        self.last_reading_skipped = False
        self.last_error_defined = not self._after_skip
        self._after_skip = False
        if self._last_prediction is None:
            err = 0.0
        else:
            err = math.sqrt(
                sum((a - b) ** 2 for a, b in zip(feature, self._last_prediction))
            )
        self._last_prediction = [0.5 * v for v in feature]
        self._last_null_prediction = (
            [0.25 * v for v in feature] if null_context is not None else None
        )
        return err


def test_top_down_blend_disagreement_uses_previous_gap():
    inner = FakeInner()
    blend = TopDownBlend(inner, window=32, lr=0.05)
    context = [0.3] * 24
    null_context = [0.3] * 24
    prediction = [0.2] * 24
    gap_changed = False

    for i in range(10):
        feature = [0.1 * i + 0.05 * k for k in range(4)]
        gap_before = blend._pending_gap
        blend.step(
            feature,
            context=context,
            null_context=null_context,
            sequence_prediction=prediction,
        )
        gap_after = blend._pending_gap

        if gap_before is not None and gap_after is not None:
            if abs(gap_after - gap_before) > 1e-9:
                gap_changed = True

        if 3 <= i <= 8:
            assert blend.last_disagreement is not None
            mean_error = sum(blend._blend_errors) / len(blend._blend_errors)
            expected = gap_before / mean_error
            assert blend.last_disagreement == pytest.approx(expected, abs=1e-9)

    assert gap_changed
