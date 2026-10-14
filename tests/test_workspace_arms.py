# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from datetime import datetime, timezone

import pytest

from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.context import BroadcastContext, featurize_events
from kaine.workspace import (
    NoveltyTracker,
    RuleBasedSalience,
    StaticAffectModulator,
    StaticGoalScorer,
    Workspace,
)
from kaine.workspace.coherence import CoherenceScorer


def _ev(
    intensity: float,
    eid: str,
    tick: int = 0,
    source: str = "interoception",
) -> tuple[str, Event]:
    return eid, Event(
        source=source,
        type=f"t.{eid}",
        payload={"id": eid, "tick": tick},
        salience=intensity,
        timestamp=datetime.now(timezone.utc),
    )


def _tick(n: int, tick: int, low: float = 0.05, step: float = 0.05) -> list[tuple[str, Event]]:
    events = [_ev(low + step * i, f"e{i}", tick) for i in range(n)]
    events.sort(key=lambda item: (item[1].source, item[1].type, item[0]))
    return events


def _syn(
    arm: str = "competitive",
    seed: int | None = None,
    top_k: int = 5,
    threshold: float = 0.35,
    coherence: CoherenceScorer | None = None,
) -> Workspace:
    return Workspace(
        strategy=RuleBasedSalience(
            novelty=NoveltyTracker(window=64),
            goal_scorer=StaticGoalScorer(),
            affect_modulator=StaticAffectModulator(),
        ),
        top_k=top_k,
        publication_threshold=threshold,
        arm=arm,
        arm_seed=seed,
        coherence=coherence,
    )


@pytest.mark.asyncio
async def test_default_arm_is_competitive():
    syn = _syn()
    assert syn.arm == "competitive"

    events = _tick(10, 0)
    ctx = {"tick_index": 0, "is_experiential": True}
    snap = await syn.select(events, ctx)
    explicit = await _syn(arm="competitive").select(events, ctx)

    ids = [eid for eid, _ in snap.selected_events]
    assert ids == [eid for eid, _ in explicit.selected_events]
    assert snap.inhibited == explicit.inhibited
    assert snap.salience_scores == explicit.salience_scores

    expected_ids = [
        eid
        for eid, _ in sorted(events, key=lambda item: item[1].salience, reverse=True)[:5]
    ]
    assert ids == expected_ids
    assert snap.inhibited is False
    assert snap.metadata["arm"] == "competitive"
    assert snap.metadata["access_threshold"] == pytest.approx(0.35)


@pytest.mark.asyncio
async def test_matched_coalition_size_equals_competitive():
    for n in (1, 3, 5, 12):
        events = _tick(n, n)
        ctx = {"tick_index": n, "is_experiential": True}
        comp = await _syn().select(events, ctx)
        matched = await _syn(arm="matched", seed=1).select(events, ctx)
        size = min(5, n)
        assert len(comp.selected_events) == size
        assert len(matched.selected_events) == size


@pytest.mark.asyncio
async def test_matched_score_table_equals_competitive():
    events = _tick(12, 0)
    ctx = {"tick_index": 0, "is_experiential": True}
    comp = await _syn().select(events, ctx)
    matched = await _syn(arm="matched", seed=1).select(events, ctx)
    assert comp.salience_scores == matched.salience_scores
    assert set(comp.salience_scores) == {eid for eid, _ in events}


@pytest.mark.asyncio
async def test_matched_draw_ignores_score():
    syn = _syn(arm="matched", seed=3)
    differing = False
    for t in range(30):
        events = _tick(20, t)
        ctx = {"tick_index": t, "is_experiential": True}
        snap = await syn.select(events, ctx)
        ids = [eid for eid, _ in snap.selected_events]
        expected_top = [
            eid
            for eid, _ in sorted(events, key=lambda item: item[1].salience, reverse=True)[:5]
        ]
        if set(ids) != set(expected_top):
            differing = True
        scores = [snap.salience_scores[eid] for eid in ids]
        assert scores == sorted(scores, reverse=True)
    assert differing


@pytest.mark.asyncio
async def test_matched_same_seed_reproduces_and_seed_matters():
    syn_a = _syn(arm="matched", seed=7)
    syn_b = _syn(arm="matched", seed=7)
    syn_c = _syn(arm="matched", seed=8)
    a_ids = []
    b_ids = []
    c_ids = []
    for t in range(10):
        events = _tick(20, t)
        ctx = {"tick_index": t, "is_experiential": True}
        a_ids.append([eid for eid, _ in (await syn_a.select(events, ctx)).selected_events])
        b_ids.append([eid for eid, _ in (await syn_b.select(events, ctx)).selected_events])
        c_ids.append([eid for eid, _ in (await syn_c.select(events, ctx)).selected_events])
    assert a_ids == b_ids
    assert any(a != c for a, c in zip(a_ids, c_ids))


@pytest.mark.asyncio
async def test_matched_non_broadcast_ticks_draw_nothing():
    syn_a = _syn(arm="matched", seed=5)
    syn_b = _syn(arm="matched", seed=5)
    broadcast_ticks = {2, 5, 8, 11}
    a_sets = {}
    b_sets = {}
    for i in range(12):
        events = _tick(20, i)
        ctx = {"tick_index": i, "is_experiential": i in broadcast_ticks}
        snap = await syn_a.select(events, ctx)
        if i in broadcast_ticks:
            a_sets[i] = {eid for eid, _ in snap.selected_events}
    for i in sorted(broadcast_ticks):
        events = _tick(20, i)
        ctx = {"tick_index": i, "is_experiential": True}
        snap = await syn_b.select(events, ctx)
        b_sets[i] = {eid for eid, _ in snap.selected_events}
    assert a_sets == b_sets


@pytest.mark.asyncio
async def test_matched_access_follows_threshold_within_draw():
    syn = _syn(arm="matched", seed=11, threshold=0.35)
    saw_inhibited_with_hi = False
    for t in range(40):
        hi = _ev(0.9, "hi", t)
        los = [_ev(0.1, f"lo{i}", t) for i in range(1, 12)]
        events = [hi, *los]
        events.sort(key=lambda item: (item[1].source, item[1].type, item[0]))
        ctx = {"tick_index": t, "is_experiential": True}
        snap = await syn.select(events, ctx)
        selected_scores = [snap.salience_scores[eid] for eid, _ in snap.selected_events]
        assert snap.inhibited == all(s < 0.35 for s in selected_scores)
        if snap.inhibited and max(snap.salience_scores.values()) >= 0.35:
            saw_inhibited_with_hi = True
    assert saw_inhibited_with_hi


@pytest.mark.asyncio
async def test_pooled_admits_every_candidate_without_scoring():
    class NoScoreStrategy:
        async def score(self, event, context):
            raise AssertionError("pooled arm must not score")

    syn = Workspace(
        strategy=NoScoreStrategy(),
        top_k=5,
        publication_threshold=0.35,
        arm="pooled",
    )
    events = _tick(12, 0, low=0.05, step=0.05)
    ctx = {"tick_index": 0, "is_experiential": True}
    snap = await syn.select(events, ctx)

    assert [eid for eid, _ in snap.selected_events] == [eid for eid, _ in events]
    assert snap.inhibited is False
    assert snap.salience_scores == {eid: ev.salience for eid, ev in events}
    assert snap.metadata == {"arm": "pooled"}


@pytest.mark.asyncio
async def test_pooled_empty_tick_is_not_inhibited():
    syn = _syn(arm="pooled")
    ctx = {"tick_index": 0, "is_experiential": True}
    snap = await syn.select([], ctx)
    assert snap.selected_events == []
    assert snap.inhibited is False
    assert snap.metadata == {"arm": "pooled"}


@pytest.mark.asyncio
async def test_competitive_and_matched_empty_ticks_are_inhibited_and_name_the_arm():
    for arm in ("competitive", "matched"):
        syn = _syn(arm=arm, seed=1)
        ctx = {"tick_index": 0, "is_experiential": True}
        snap = await syn.select([], ctx)
        assert snap.inhibited is True
        assert snap.metadata["arm"] == arm


@pytest.mark.asyncio
async def test_matched_requires_the_broadcast_flag():
    syn = _syn(arm="matched", seed=1)
    with pytest.raises(ValueError):
        await syn.select(_tick(3, 0), {"tick_index": 0})
    snap = await syn.select(_tick(3, 1), {"tick_index": 1, "is_experiential": False})
    assert len(snap.selected_events) == 3


def test_arm_validation():
    with pytest.raises(ValueError):
        _syn(arm="random")
    with pytest.raises(ValueError):
        _syn(arm="matched", seed=None)
    with pytest.raises(ValueError):
        _syn(
            arm="matched",
            seed=1,
            coherence=CoherenceScorer(
                plv_window=12,
                coherence_floor=0.5,
                coherence_ceiling=1.5,
            ),
        )
    with pytest.raises(ValueError):
        _syn(
            arm="pooled",
            coherence=CoherenceScorer(
                plv_window=12,
                coherence_floor=0.5,
                coherence_ceiling=1.5,
            ),
        )


@pytest.mark.asyncio
async def test_pooled_context_takes_every_member():
    events = [
        _ev(0.1, "a", source="interoception"),
        _ev(0.2, "b", source="vision"),
        _ev(0.5, "c", source="sequence"),
        _ev(0.9, "d", source="affect"),
    ]
    snapshot = await _syn(arm="pooled").select(events, {"tick_index": 1, "is_experiential": True})
    ctx = BroadcastContext(lambda: 10.0)
    assert ctx.observe(snapshot) is True
    expected = featurize_events([(ev.source, ev.type, ev.salience) for _, ev in events], 0.0)
    assert ctx.vector() == expected


def test_empty_pooled_broadcast_replaces_context():
    events = [_ev(0.1, "a"), _ev(0.2, "b"), _ev(0.3, "c")]
    snapshot = WorkspaceSnapshot(
        tick_index=1,
        selected_events=events,
        inhibited=False,
        salience_scores={eid: float(ev.salience) for eid, ev in events},
        metadata={"arm": "pooled"},
    )
    ctx = BroadcastContext(lambda: 10.0)
    assert ctx.observe(snapshot) is True
    empty = WorkspaceSnapshot(
        tick_index=2,
        selected_events=[],
        inhibited=False,
        salience_scores={},
        metadata={"arm": "pooled"},
    )
    assert ctx.observe(empty) is True
    assert ctx.vector() == featurize_events([], 0.0)


def test_competitive_broadcast_without_accessed_member_keeps_context():
    snapshot = WorkspaceSnapshot(
        tick_index=1,
        selected_events=[_ev(0.1, "a")],
        inhibited=False,
        salience_scores={"a": 0.1},
        metadata={"access_threshold": 0.35, "arm": "competitive"},
    )
    ctx = BroadcastContext(lambda: 10.0)
    assert ctx.observe(snapshot) is False
    assert ctx.has_context is False


@pytest.mark.asyncio
async def test_matched_context_holds_only_accessed_drawn_members():
    syn = _syn(arm="matched", seed=2, threshold=0.35)
    saw_access = False
    for t in range(10):
        events = _tick(12, t, low=0.05, step=0.05)
        ctx = {"tick_index": t, "is_experiential": True}
        snap = await syn.select(events, ctx)
        if snap.inhibited:
            fresh = BroadcastContext(lambda: 10.0)
            assert fresh.observe(snap) is False
        else:
            saw_access = True
            accessed = [
                (ev.source, ev.type, float(ev.salience))
                for eid, ev in snap.selected_events
                if snap.salience_scores[eid] >= 0.35
            ]
            fresh = BroadcastContext(lambda: 10.0)
            assert fresh.observe(snap) is True
            assert fresh.vector() == featurize_events(accessed, 0.0)
    assert saw_access
