# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for stream-qualified salience score keys."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from kaine.bus.client import AsyncBus, _encode_event
from kaine.bus.config import BusConfig
from kaine.bus.schema import (
    WORKSPACE_STREAM,
    Event,
    entry_id_sort_key,
    split_stream_entry_key,
    stream_entry_key,
)
from kaine.cycle import CognitiveCycle
from kaine.cycle.types import WorkspaceSnapshot
from kaine.evaluation.observers.research_event_observer import (
    ResearchEventObserver,
    _workspace_metadata_record,
)
from kaine.evaluation.sink import AsyncJsonlSink
from kaine.experiment.tone_analysis import tone_events
from kaine.modules.context import BroadcastContext
from kaine.workspace import (
    NoveltyTracker,
    RuleBasedSalience,
    StaticAffectModulator,
    StaticGoalScorer,
    Workspace,
)
from kaine.workspace.coherence import CoherenceScorer
from tests._fakes import FakeClock, FakeRegistry, FakeWorkspace

fakeredis = pytest.importorskip("fakeredis.aioredis")


def _strategy():
    return RuleBasedSalience(
        novelty=NoveltyTracker(window=64),
        goal_scorer=StaticGoalScorer(),
        affect_modulator=StaticAffectModulator(),
    )


def _interoception_event(salience=0.9):
    return Event(
        source="interoception",
        type="interoception.report",
        payload={"body": "interoception"},
        salience=salience,
        timestamp=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
    )


def _vision_event(salience=0.1):
    return Event(
        source="vision",
        type="vision.report",
        payload={"place": "vision"},
        salience=salience,
        timestamp=datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc),
    )


def _make_cycle(workspace, registry_streams, client):
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    clock = FakeClock()
    return CognitiveCycle(
        bus=bus,
        workspace=workspace,
        registry=FakeRegistry(registry_streams),
        processing_rate_hz=10.0,
        experiential_rate_hz=10.0,
        clock=clock,
        sleep=clock.sleep,
    ), bus


@pytest.mark.parametrize(
    "arm,arm_seed",
    [
        ("competitive", None),
        ("matched", 1),
        ("pooled", None),
    ],
)
@pytest.mark.asyncio
async def test_scores_from_two_streams_with_one_entry_id_both_survive(arm, arm_seed):
    client = fakeredis.FakeRedis(decode_responses=True)
    kwargs = {"arm": arm}
    if arm_seed is not None:
        kwargs["arm_seed"] = arm_seed
    syn = Workspace(
        strategy=_strategy(),
        top_k=5,
        publication_threshold=0.35,
        **kwargs,
    )
    cycle, bus = _make_cycle(syn, ["interoception.out", "vision.out"], client)
    try:
        await client.xadd("interoception.out", _encode_event(_interoception_event()), id="1760000000000-0")
        await client.xadd("vision.out", _encode_event(_vision_event()), id="1760000000000-0")
        result = await cycle.tick()
        assert result.is_experiential
        entries = await client.xrange(WORKSPACE_STREAM)
        assert len(entries) == 1
        _entry_id, fields = entries[0]
        snap = json.loads(fields["snapshot"])
        assert set(snap["salience_scores"]) == {
            "interoception.out:1760000000000-0",
            "vision.out:1760000000000-0",
        }
        selected = snap["selected"]
        assert len(selected) == 2
        for item in selected:
            entry_id = item["entry_id"]
            assert entry_id in snap["salience_scores"]
        scores = snap["salience_scores"]
        assert scores["interoception.out:1760000000000-0"] > scores["vision.out:1760000000000-0"]
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_broadcast_context_reads_each_members_own_score():
    client = fakeredis.FakeRedis(decode_responses=True)
    syn = Workspace(
        strategy=_strategy(),
        top_k=5,
        publication_threshold=0.35,
        arm="competitive",
    )
    cycle, bus = _make_cycle(syn, ["interoception.out", "vision.out"], client)
    try:
        await client.xadd("interoception.out", _encode_event(_interoception_event()), id="1760000000000-0")
        await client.xadd("vision.out", _encode_event(_vision_event()), id="1760000000000-0")
        await cycle.tick()
        entries = await client.xrange(WORKSPACE_STREAM)
        assert len(entries) == 1
        _entry_id, fields = entries[0]
        snap = json.loads(fields["snapshot"])
        selected_events = [
            (
                item["entry_id"],
                Event(
                    source=item["source"],
                    type=item["type"],
                    payload=item["payload"],
                    salience=item["salience"],
                    timestamp=datetime.fromisoformat(item["timestamp"]),
                ),
            )
            for item in snap["selected"]
        ]
        snapshot = WorkspaceSnapshot(
            tick_index=snap["tick_index"],
            selected_events=selected_events,
            inhibited=snap["inhibited"],
            salience_scores=snap["salience_scores"],
            metadata=snap["metadata"],
        )
        ctx = BroadcastContext(clock=lambda: 0.0)
        adopted = ctx.observe(snapshot)
        assert adopted is True
        assert ctx._members == [("interoception", "interoception.report", 0.9)]
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_candidates_are_ordered_by_source_first():
    client = fakeredis.FakeRedis(decode_responses=True)
    syn = FakeWorkspace()
    cycle, bus = _make_cycle(syn, ["vision.out", "interoception.out"], client)
    try:
        vision_event = Event(
            source="vision",
            type="vision.report",
            payload={"order": "third"},
            salience=0.5,
            timestamp=datetime(2026, 1, 1, 0, 0, 2, tzinfo=timezone.utc),
        )
        interoception_first = Event(
            source="interoception",
            type="interoception.report",
            payload={"order": "first"},
            salience=0.5,
            timestamp=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        )
        interoception_second = Event(
            source="interoception",
            type="interoception.report",
            payload={"order": "second"},
            salience=0.5,
            timestamp=datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc),
        )
        await client.xadd("vision.out", _encode_event(vision_event), id="1760000000000-0")
        await client.xadd("interoception.out", _encode_event(interoception_first), id="1760000000000-0")
        await client.xadd("interoception.out", _encode_event(interoception_second), id="1760000000000-1")
        await cycle.tick()
        assert len(syn.calls) == 1
        events = syn.calls[0]["events"]
        ids = [entry_id for entry_id, _ in events]
        assert ids == [
            "interoception.out:1760000000000-0",
            "interoception.out:1760000000000-1",
            "vision.out:1760000000000-0",
        ]
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_entry_id_orders_before_stream():
    client = fakeredis.FakeRedis(decode_responses=True)
    syn = FakeWorkspace()
    cycle, bus = _make_cycle(syn, ["a.out", "b.out"], client)
    try:
        a_event = Event(
            source="interoception",
            type="interoception.report",
            payload={"stream": "a"},
            salience=0.5,
            timestamp=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        )
        b_event = Event(
            source="interoception",
            type="interoception.report",
            payload={"stream": "b"},
            salience=0.5,
            timestamp=datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc),
        )
        await client.xadd("a.out", _encode_event(a_event), id="1760000000000-1")
        await client.xadd("b.out", _encode_event(b_event), id="1760000000000-0")
        await cycle.tick()
        assert len(syn.calls) == 1
        events = syn.calls[0]["events"]
        ids = [entry_id for entry_id, _ in events]
        # The bus entry id orders before the stream, which is only a final tie-break.
        assert ids == [
            "b.out:1760000000000-0",
            "a.out:1760000000000-1",
        ]
    finally:
        await bus.close()


@pytest.mark.parametrize("arm", ["competitive", "matched", "pooled"])
@pytest.mark.asyncio
async def test_duplicate_candidate_ids_are_refused(arm):
    kwargs = {"arm": arm}
    if arm == "matched":
        kwargs["arm_seed"] = 1
    syn = Workspace(
        strategy=_strategy(),
        top_k=5,
        publication_threshold=0.35,
        **kwargs,
    )
    now = datetime.now(timezone.utc)
    ev1 = Event(
        source="interoception",
        type="interoception.report",
        payload={},
        salience=0.9,
        timestamp=now,
    )
    ev2 = Event(
        source="vision",
        type="vision.report",
        payload={},
        salience=0.1,
        timestamp=now,
    )
    with pytest.raises(ValueError):
        await syn.select(
            [("a", ev1), ("a", ev2)],
            {"tick_index": 0, "is_experiential": True},
        )


def test_stream_entry_key_round_trip():
    key = stream_entry_key("interoception.out", "1760000000000-0")
    assert key == "interoception.out:1760000000000-0"
    assert split_stream_entry_key(key) == ("interoception.out", "1760000000000-0")
    assert split_stream_entry_key("1760000000000-0") == (None, "1760000000000-0")


@pytest.mark.asyncio
async def test_select_dual_refuses_duplicate_candidate_ids():
    ctx = {
        "tick_index": 0,
        "is_experiential": True,
        "phases": {"interoception": 0.0, "vision": 1.0},
    }
    syne = Workspace(
        strategy=_strategy(),
        top_k=5,
        publication_threshold=0.35,
        coherence=CoherenceScorer(
            plv_window=12, coherence_floor=0.5, coherence_ceiling=1.5
        ),
    )
    with pytest.raises(ValueError):
        await syne.select_dual([("a", _interoception_event()), ("a", _vision_event())], ctx)


@pytest.mark.asyncio
async def test_select_dual_keeps_one_score_per_candidate():
    ctx = {
        "tick_index": 0,
        "is_experiential": True,
        "phases": {"interoception": 0.0, "vision": 1.0},
    }
    syne = Workspace(
        strategy=_strategy(),
        top_k=5,
        publication_threshold=0.35,
        coherence=CoherenceScorer(
            plv_window=12, coherence_floor=0.5, coherence_ceiling=1.5
        ),
    )
    ids = ["interoception.out:1760000000000-0", "vision.out:1760000000000-0"]
    primary, counterfactual = await syne.select_dual(
        [(ids[0], _interoception_event()), (ids[1], _vision_event())], ctx
    )
    assert counterfactual is not None
    for snapshot in (primary, counterfactual):
        assert set(snapshot.salience_scores.keys()) == set(ids)
        for event_id, _event in snapshot.selected_events:
            assert event_id in snapshot.salience_scores


@pytest.mark.asyncio
async def test_entry_ids_order_numerically_within_a_millisecond():
    client = fakeredis.FakeRedis(decode_responses=True)
    syn = FakeWorkspace()
    cycle, bus = _make_cycle(syn, ["interoception.out"], client)
    try:
        for i in range(12):
            event = Event(
                source="interoception",
                type="interoception.report",
                payload={"i": i},
                salience=0.5,
                timestamp=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            )
            await client.xadd("interoception.out", _encode_event(event), id=f"1760000000000-{i}")
        await cycle.tick()
        assert len(syn.calls) == 1
        events = syn.calls[0]["events"]
        ids = [entry_id for entry_id, _ in events]
        assert ids == [f"interoception.out:1760000000000-{i}" for i in range(12)]
    finally:
        await bus.close()


def test_entry_id_sort_key():
    assert entry_id_sort_key("1760000000000-2") < entry_id_sort_key("1760000000000-10")
    assert entry_id_sort_key("1760000000000-11") < entry_id_sort_key("1760000000001-0")
    assert entry_id_sort_key("e1") == (1, 0, 0, "e1")
    assert entry_id_sort_key("9999999999999-99") < entry_id_sort_key("e1")


@pytest.mark.asyncio
async def test_tone_event_is_accessed_through_the_engine_path(tmp_path):
    client = fakeredis.FakeRedis(decode_responses=True)
    workspace = Workspace(
        strategy=_strategy(),
        top_k=5,
        publication_threshold=0.35,
    )
    cycle, bus = _make_cycle(workspace, ["audition.out", "interoception.out"], client)

    tone_event = Event(
        source="audition",
        type="audition.emotion",
        salience=0.9,
        timestamp=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        payload={
            "category": "happy",
            "confidence": 0.9,
            "scores": {"happy": 0.9},
            "alert": False,
            "tone_error_ratio": 0.5,
            "tone_rule": "error_ratio",
            "classified": True,
        },
    )

    try:
        await client.xadd(
            "audition.out", _encode_event(tone_event), id="1760000000000-0"
        )
        await client.xadd(
            "interoception.out", _encode_event(_interoception_event(0.1)), id="1760000000000-0"
        )
        result = await cycle.tick()
        assert result.is_experiential

        # Build the research records the research log would write.
        observer = ResearchEventObserver(
            bus=None, sink=AsyncJsonlSink(tmp_path / "re", name="research_events")
        )
        written = []

        class _FakeSink:
            async def write(self, record):
                written.append(record)

        observer._sink = _FakeSink()
        await observer.handle("audition.out", "1760000000000-0", tone_event)
        tone_record = written[0]

        entries = await client.xrange(WORKSPACE_STREAM)
        assert len(entries) == 1
        _entry_id, fields = entries[0]
        broadcast_record = _workspace_metadata_record(json.loads(fields["snapshot"]))

        events = tone_events([tone_record, broadcast_record])
        assert len(events) == 1
        assert events[0].accessed is True
        assert events[0].entry_id == "audition.out:1760000000000-0"
        # With ids keyed by entry id alone, the interoception module's 0.1 overwrote the tone
        # event's score and the tone event read as not accessed.
    finally:
        await bus.close()


async def _matched_coalitions(seed):
    client = fakeredis.FakeRedis(decode_responses=True)
    syn = Workspace(
        strategy=_strategy(),
        top_k=2,
        publication_threshold=0.35,
        arm="matched",
        arm_seed=seed,
    )
    cycle, bus = _make_cycle(syn, ["interoception.out", "vision.out"], client)
    try:
        base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        for i in range(12):
            event = Event(
                source="interoception",
                type="interoception.report",
                payload={"i": i},
                salience=0.1 + 0.05 * i,
                timestamp=base.replace(second=i),
            )
            await client.xadd(
                "interoception.out", _encode_event(event), id=f"1760000000000-{i}"
            )
        for i in range(3):
            event = Event(
                source="vision",
                type="vision.report",
                payload={"j": i},
                salience=0.5,
                timestamp=base.replace(second=12 + i),
            )
            await client.xadd(
                "vision.out", _encode_event(event), id=f"1760000000000-{i}"
            )
        result = await cycle.tick()
        assert result.is_experiential
        entries = await client.xrange(WORKSPACE_STREAM)
        assert len(entries) == 1
        _entry_id, fields = entries[0]
        snap = json.loads(fields["snapshot"])
        return [item["entry_id"] for item in snap["selected"]]
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_matched_draw_is_reproducible_over_the_new_order():
    # Matched selection must be deterministic for a fixed seed.
    first = await _matched_coalitions(4)
    second = await _matched_coalitions(4)
    assert first == second
    assert len(first) == 2
    for entry_id in first:
        assert entry_id.startswith(("interoception.out:", "vision.out:"))


@pytest.mark.asyncio
async def test_read_cursors_stay_raw_bus_ids():
    client = fakeredis.FakeRedis(decode_responses=True)
    syn = Workspace(strategy=_strategy(), arm="competitive")
    cycle, bus = _make_cycle(syn, ["interoception.out", "vision.out"], client)
    try:
        await client.xadd(
            "interoception.out", _encode_event(_interoception_event()), id="1760000000000-0"
        )
        await client.xadd(
            "vision.out", _encode_event(_vision_event()), id="1760000000000-0"
        )
        await cycle.tick()
        assert cycle._cursors == {
            "interoception.out": "1760000000000-0",
            "vision.out": "1760000000000-0",
        }
        for value in cycle._cursors.values():
            assert ":" not in value
        # The stream-qualified name is only the candidate's id; the read
        # cursor must stay the raw bus id, or the next XREAD would fail.
    finally:
        await bus.close()
