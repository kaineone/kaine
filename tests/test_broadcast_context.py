# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import math
from datetime import datetime, timezone

import pytest

from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.chronos.featurizer import SnapshotFeaturizer
from kaine.modules.context import (
    ADDITIVE_INDICES,
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


def test_null_replaces_only_other_sources_by_their_running_mean():
    clock = [0.0]

    def tick():
        clock[0] += 1.0
        return clock[0]

    ctx = BroadcastContext(clock=tick)

    broadcasts = [
        [
            ("topos", "topos.report", 0.5),
            ("soma", "soma.report", 0.125),
            ("audition", "audition.report", 0.25),
            ("lingua", "lingua.report", 0.375),
        ],
        [
            ("topos", "topos.report", 0.75),
            ("soma", "soma.report", 0.875),
            ("audition", "audition.report", 0.5),
            ("praxis", "praxis.report", 0.625),
        ],
        [
            ("topos", "topos.report", 0.25),
            ("soma", "soma.report", 0.5),
            ("soma", "soma.report", 0.625),
            ("audition", "audition.report", 0.125),
            ("lingua", "lingua.report", 0.375),
        ],
    ]

    def _snapshot(tick_index, members):
        selected_events = []
        salience_scores = {}
        for j, (source, type_, weight) in enumerate(members):
            eid = f"{tick_index}-{j}"
            selected_events.append((eid, _ev(source, type_, weight)))
            salience_scores[eid] = weight
        return WorkspaceSnapshot(
            tick_index=tick_index,
            selected_events=selected_events,
            inhibited=False,
            salience_scores=salience_scores,
            metadata={"access_threshold": 0.0},
            is_experiential=True,
        )

    for idx, members in enumerate(broadcasts):
        assert ctx.observe(_snapshot(idx, members)) is True

    b, null = ctx.context_and_null({"topos"})
    assert null is not b

    topos_current = featurize_events(
        [(s, t, w) for (s, t, w) in broadcasts[2] if s == "topos"], 0.0
    )
    non_topos_means = [
        sum(
            featurize_events(
                [(s, t, w) for (s, t, w) in broadcast if s != "topos"], 0.0
            )[i]
            for broadcast in broadcasts
        ) / len(broadcasts)
        for i in range(len(b))
    ]
    for i in ADDITIVE_INDICES:
        assert null[i] == pytest.approx(topos_current[i] + non_topos_means[i])

    all_means = [
        sum(
            featurize_events(broadcast, 0.0)[i]
            for broadcast in broadcasts
        ) / len(broadcasts)
        for i in range(len(b))
    ]
    for i in range(4):
        assert null[i] == pytest.approx(all_means[i])

    for i in (20, 21, 22):
        assert null[i] == b[i]

    b2, null2 = ctx.context_and_null({"soma", "lingua"})
    kept_current = featurize_events(
        [(s, t, w) for (s, t, w) in broadcasts[2] if s in {"soma", "lingua"}], 0.0
    )
    non_kept_means = [
        sum(
            featurize_events(
                [(s, t, w) for (s, t, w) in broadcast if s not in {"soma", "lingua"}], 0.0
            )[i]
            for broadcast in broadcasts
        ) / len(broadcasts)
        for i in range(len(b2))
    ]
    for i in ADDITIVE_INDICES:
        assert null2[i] == pytest.approx(kept_current[i] + non_kept_means[i])
    for i in range(4):
        assert null2[i] == pytest.approx(all_means[i])
    for i in (20, 21, 22):
        assert null2[i] == b2[i]


def test_null_equals_context_when_other_sources_never_vary():
    clock = [0.0]

    def tick():
        clock[0] += 1.0
        return clock[0]

    ctx = BroadcastContext(clock=tick)

    members = [
        ("topos", "topos.report", 0.5),
        ("soma", "soma.report", 0.25),
        ("audition", "audition.report", 0.75),
    ]

    def _snapshot(tick_index, members):
        selected_events = []
        salience_scores = {}
        for j, (source, type_, weight) in enumerate(members):
            eid = f"{tick_index}-{j}"
            selected_events.append((eid, _ev(source, type_, weight)))
            salience_scores[eid] = weight
        return WorkspaceSnapshot(
            tick_index=tick_index,
            selected_events=selected_events,
            inhibited=False,
            salience_scores=salience_scores,
            metadata={"access_threshold": 0.0},
            is_experiential=True,
        )

    for i in range(3):
        assert ctx.observe(_snapshot(i, members)) is True

    b, null = ctx.context_and_null({"topos"})
    assert null == b


def test_context_and_null_before_adoption():
    ctx = BroadcastContext(clock=lambda: 0.0)
    assert ctx.context_and_null({"topos"}) == (None, None)
