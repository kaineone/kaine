# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import math
from datetime import datetime, timezone

import pytest

from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.chronos.featurizer import SnapshotFeaturizer
from kaine.modules.context import (
    BroadcastContext,
    featurize_events,
)


def _ev(source, type_, salience, **payload):
    return Event(
        source=source,
        type=type_,
        payload=payload or {"k": 1},
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )


def test_featurize_matches_chronos_featurizer():
    events = [
        ("topos", "topos.report", 0.7),
        ("audition", "audition.perception", 0.6),
        ("hypnos", "hypnos.sleep", 0.1),
        ("soma", "soma.report", 0.3),
    ]
    ctx_vec = featurize_events(events, age_s=0.0)

    selected = [
        (f"{i}-0", _ev(source, type_, salience))
        for i, (source, type_, salience) in enumerate(events)
    ]
    snapshot = WorkspaceSnapshot(
        tick_index=0,
        selected_events=selected,
        inhibited=False,
        salience_scores={entry_id: float(ev.salience) for entry_id, ev in selected},
        metadata={"access_threshold": 0.0},
        is_experiential=True,
    )
    chrono_vec = SnapshotFeaturizer(clock=lambda: 0.0).featurize(snapshot)

    for i in list(range(20)) + [23]:
        assert ctx_vec[i] == pytest.approx(chrono_vec[i])


def test_inhibited_broadcast_is_not_adopted():
    ctx = BroadcastContext(clock=lambda: 0.0)

    accessed = WorkspaceSnapshot(
        tick_index=0,
        selected_events=[("1-0", _ev("topos", "topos.report", 0.5))],
        inhibited=False,
        salience_scores={"1-0": 0.5},
        metadata={"access_threshold": 0.35},
        is_experiential=True,
    )
    assert ctx.observe(accessed) is True

    inhibited = WorkspaceSnapshot(
        tick_index=1,
        selected_events=[("2-0", _ev("soma", "soma.report", 0.9))],
        inhibited=True,
        salience_scores={"2-0": 0.9},
        metadata={"access_threshold": 0.35},
        is_experiential=True,
    )
    assert ctx.observe(inhibited) is False

    vec = ctx.vector()
    assert vec is not None
    assert vec[4 + 2] == pytest.approx(0.5)  # topos bin
    assert vec[4 + 0] == pytest.approx(0.0)  # soma bin


def test_riders_below_threshold_are_excluded():
    ctx = BroadcastContext(clock=lambda: 0.0)
    snapshot = WorkspaceSnapshot(
        tick_index=0,
        selected_events=[
            ("1-0", _ev("topos", "topos.report", 0.5)),
            ("2-0", _ev("thymos", "thymos.report", 0.1)),
        ],
        inhibited=False,
        salience_scores={"1-0": 0.5, "2-0": 0.1},
        metadata={"access_threshold": 0.35},
        is_experiential=True,
    )
    assert ctx.observe(snapshot) is True

    vec = ctx.vector()
    assert vec[4 + 2] == pytest.approx(0.5)  # topos
    assert vec[4 + 5] == pytest.approx(0.0)  # thymos


def test_null_vector_keeps_kept_share_and_averages_the_rest():
    clock = [0.0]

    def tick():
        return clock[0]

    ctx = BroadcastContext(clock=tick)

    first = WorkspaceSnapshot(
        tick_index=0,
        selected_events=[
            ("1-0", _ev("topos", "topos.report", 0.7)),
            ("2-0", _ev("soma", "soma.report", 0.3)),
        ],
        inhibited=False,
        salience_scores={"1-0": 0.7, "2-0": 0.3},
        metadata={"access_threshold": 0.0},
        is_experiential=True,
    )
    clock[0] = 1.0
    assert ctx.observe(first) is True

    second = WorkspaceSnapshot(
        tick_index=1,
        selected_events=[
            ("3-0", _ev("topos", "topos.report", 0.5)),
            ("4-0", _ev("soma", "soma.report", 0.9)),
        ],
        inhibited=False,
        salience_scores={"3-0": 0.5, "4-0": 0.9},
        metadata={"access_threshold": 0.0},
        is_experiential=True,
    )
    clock[0] = 2.0
    assert ctx.observe(second) is True

    null = ctx.null_vector(kept_sources={"topos"})
    assert null is not None

    # Kept source uses the current context's share.
    assert null[4 + 2] == pytest.approx(0.5)  # current topos
    # Dropped source uses the running mean over adopted contexts.
    assert null[4 + 0] == pytest.approx((0.3 + 0.9) / 2)  # mean soma
    # Components 0..3 are running means.
    assert null[0] == pytest.approx(math.log1p(2))
    assert null[1] == pytest.approx((0.5 + 0.7) / 2)
    assert null[2] == pytest.approx((0.7 + 0.9) / 2)
    assert null[3] == pytest.approx(
        (math.sqrt(0.08) + math.sqrt(0.08)) / 2, rel=1e-5
    )
    assert null[22] == pytest.approx(1.0)


def test_age_grows_with_the_clock():
    clock = [0.0]

    def tick():
        return clock[0]

    ctx = BroadcastContext(clock=tick)
    snapshot = WorkspaceSnapshot(
        tick_index=0,
        selected_events=[("1-0", _ev("topos", "topos.report", 0.5))],
        inhibited=False,
        salience_scores={"1-0": 0.5},
        metadata={"access_threshold": 0.0},
        is_experiential=True,
    )
    assert ctx.observe(snapshot) is True

    clock[0] = 3.0
    assert ctx.vector()[20] == pytest.approx(math.log1p(3.0))
    assert ctx.age_s() == pytest.approx(3.0)


def test_age_counts_from_publication():
    clock = [12.5]

    def tick():
        return clock[0]

    ctx = BroadcastContext(clock=tick)
    snapshot = WorkspaceSnapshot(
        tick_index=0,
        selected_events=[("1-0", _ev("topos", "topos.report", 0.5))],
        inhibited=False,
        salience_scores={"1-0": 0.5},
        metadata={"access_threshold": 0.0},
        is_experiential=True,
        published_at=10.0,
    )
    assert ctx.observe(snapshot) is True
    assert ctx.age_s() == pytest.approx(2.5)
    assert ctx.vector()[20] == pytest.approx(math.log1p(2.5))


def test_age_falls_back_to_receipt_without_publication_time():
    clock = [5.0]

    def tick():
        return clock[0]

    ctx = BroadcastContext(clock=tick)
    snapshot = WorkspaceSnapshot(
        tick_index=0,
        selected_events=[("1-0", _ev("topos", "topos.report", 0.5))],
        inhibited=False,
        salience_scores={"1-0": 0.5},
        metadata={"access_threshold": 0.0},
        is_experiential=True,
    )
    assert ctx.observe(snapshot) is True
    assert ctx.age_s() == pytest.approx(0.0)

    clock[0] = 7.0
    assert ctx.age_s() == pytest.approx(2.0)


def test_age_is_never_negative():
    clock = [1.0]

    def tick():
        return clock[0]

    ctx = BroadcastContext(clock=tick)
    snapshot = WorkspaceSnapshot(
        tick_index=0,
        selected_events=[("1-0", _ev("topos", "topos.report", 0.5))],
        inhibited=False,
        salience_scores={"1-0": 0.5},
        metadata={"access_threshold": 0.0},
        is_experiential=True,
        published_at=4.0,
    )
    assert ctx.observe(snapshot) is True
    assert ctx.age_s() == 0.0


def test_no_context_before_first_adoption():
    ctx = BroadcastContext(clock=lambda: 0.0)
    assert ctx.has_context is False
    assert ctx.vector() is None
    assert ctx.null_vector({"topos"}) is None
    assert ctx.age_s() is None
