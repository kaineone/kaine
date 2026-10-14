# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the workspace-mediation measure functions and pooled snapshot."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.evaluation.benchmarks.workspace_mediation_ablation.measures import (
    headline_gain,
    mean_gain,
    sign_test_pvalue,
)
from kaine.evaluation.benchmarks.workspace_mediation_ablation.pooled import pooled_snapshot
from kaine.modules.context import BroadcastContext


def test_sign_test_all_positive_length_five():
    """All positive values of length five give a one-sided p-value of 1/32."""
    assert sign_test_pvalue([0.1] * 5) == 1 / 32


def test_sign_test_mixed_not_significant():
    """Mixed positive and negative values are not significant at the 0.05 level."""
    values = [0.1, 0.1, 0.1, 0.1, -0.1]
    assert sign_test_pvalue(values) > 0.05


def test_sign_test_drops_none_and_exact_zero():
    """None and exact zeros are excluded from the sign-test count."""
    values = [0.0, 0.1, None, 0.1, 0.1, -0.1]
    assert sign_test_pvalue(values) == 5 / 16


def test_sign_test_empty():
    """An empty effective sample returns a p-value of 1.0."""
    assert sign_test_pvalue([]) == 1.0
    assert sign_test_pvalue([None, 0.0, 0.0]) == 1.0


def test_mean_gain_averages_finite_non_none_entries():
    """The mean skips None, NaN, and infinite values and averages the rest."""
    gains = [None, 1.0, 2.0, float("nan"), float("inf"), -3.0, 4.0]
    assert mean_gain(gains, skip=1) == 1.0


def test_mean_gain_skip_drops_initial_learning_period():
    """The skip argument removes the leading entries from the average."""
    assert mean_gain([10.0, 20.0, 30.0], skip=1) == 25.0


def test_mean_gain_returns_none_when_nothing_qualifies():
    """The mean is undefined when every entry is missing or non-finite."""
    assert mean_gain([None, float("nan"), float("inf")]) is None
    assert mean_gain([1.0, 2.0], skip=5) is None


def test_mean_gain_negative_skip_raises():
    """A negative skip value is rejected."""
    with pytest.raises(ValueError):
        mean_gain([1.0], skip=-1)


def test_headline_gain_means_processors():
    """The headline gain averages per-processor gains."""
    assert headline_gain({"interoception": 1.0, "vision": 3.0}) == 2.0


def test_headline_gain_none_if_any_processor_missing():
    """The headline gain is undefined when any processor is undefined."""
    assert headline_gain({"interoception": None, "vision": 3.0}) is None


def test_headline_gain_empty():
    """An empty processor mapping has no headline gain."""
    assert headline_gain({}) is None


def test_pooled_snapshot_retains_candidates():
    """The pooled snapshot keeps every candidate with its own salience."""
    events = [
        (
            "a",
            Event(
                source="interoception",
                type="interoception.report",
                payload={},
                salience=0.1,
                timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
        ),
        (
            "b",
            Event(
                source="vision",
                type="vision.report",
                payload={},
                salience=0.9,
                timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
        ),
    ]
    snapshot = pooled_snapshot(3, events)
    assert snapshot.selected_events == events
    assert snapshot.salience_scores == {"a": 0.1, "b": 0.9}
    assert snapshot.inhibited is False
    assert snapshot.metadata.get("arm") == "pooled"
    assert "access_threshold" not in snapshot.metadata
    assert snapshot.metadata.get("candidate_count") == 2


def test_pooled_snapshot_empty():
    """An empty candidate list yields an empty, non-inhibited snapshot."""
    snapshot = pooled_snapshot(0, [])
    assert snapshot.selected_events == []
    assert snapshot.inhibited is False
    assert snapshot.salience_scores == {}
    assert snapshot.metadata.get("arm") == "pooled"


def test_broadcast_context_adopts_pooled_snapshot():
    """A pooled snapshot with three sources is adopted by BroadcastContext."""
    candidates = [
        (
            "s",
            Event(
                source="interoception",
                type="interoception.report",
                payload={},
                salience=0.6,
                timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
        ),
        (
            "t",
            Event(
                source="vision",
                type="vision.report",
                payload={},
                salience=0.7,
                timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
        ),
        (
            "c",
            Event(
                source="sequence",
                type="sequence.report",
                payload={},
                salience=0.5,
                timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
        ),
    ]
    ctx = BroadcastContext(lambda: 0.0)
    assert ctx.observe(pooled_snapshot(0, candidates)) is True
    assert ctx.has_context is True


def test_broadcast_context_rejects_thresholded_snapshot():
    """A workspace-style snapshot below its own access threshold is not adopted."""
    event = Event(
        source="interoception",
        type="interoception.report",
        payload={},
        salience=0.8,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    snapshot = WorkspaceSnapshot(
        tick_index=0,
        selected_events=[("x", event)],
        inhibited=False,
        is_experiential=True,
        salience_scores={"x": 0.1},
        metadata={"access_threshold": 0.9},
    )
    ctx = BroadcastContext(lambda: 1.0)
    assert ctx.observe(snapshot) is False
