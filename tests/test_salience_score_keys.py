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
    split_stream_entry_key,
    stream_entry_key,
)
from kaine.cycle import CognitiveCycle
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.context import BroadcastContext
from kaine.workspace import (
    NoveltyTracker,
    RuleBasedSalience,
    StaticGoalScorer,
    StaticThymosModulator,
    Syneidesis,
)
from tests._fakes import FakeClock, FakeRegistry, FakeSyneidesis

fakeredis = pytest.importorskip("fakeredis.aioredis")


def _strategy():
    return RuleBasedSalience(
        novelty=NoveltyTracker(window=64),
        goal_scorer=StaticGoalScorer(),
        thymos_modulator=StaticThymosModulator(),
    )


def _soma_event(salience=0.9):
    return Event(
        source="soma",
        type="soma.report",
        payload={"body": "soma"},
        salience=salience,
        timestamp=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
    )


def _topos_event(salience=0.1):
    return Event(
        source="topos",
        type="topos.report",
        payload={"place": "topos"},
        salience=salience,
        timestamp=datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc),
    )


def _make_cycle(syneidesis, registry_streams, client):
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    clock = FakeClock()
    return CognitiveCycle(
        bus=bus,
        syneidesis=syneidesis,
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
    syn = Syneidesis(
        strategy=_strategy(),
        top_k=5,
        publication_threshold=0.35,
        **kwargs,
    )
    cycle, bus = _make_cycle(syn, ["soma.out", "topos.out"], client)
    try:
        await client.xadd("soma.out", _encode_event(_soma_event()), id="1760000000000-0")
        await client.xadd("topos.out", _encode_event(_topos_event()), id="1760000000000-0")
        result = await cycle.tick()
        assert result.is_experiential
        entries = await client.xrange(WORKSPACE_STREAM)
        assert len(entries) == 1
        _entry_id, fields = entries[0]
        snap = json.loads(fields["snapshot"])
        assert set(snap["salience_scores"]) == {
            "soma.out:1760000000000-0",
            "topos.out:1760000000000-0",
        }
        selected = snap["selected"]
        assert len(selected) == 2
        for item in selected:
            entry_id = item["entry_id"]
            assert entry_id in snap["salience_scores"]
        scores = snap["salience_scores"]
        assert scores["soma.out:1760000000000-0"] > scores["topos.out:1760000000000-0"]
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_broadcast_context_reads_each_members_own_score():
    client = fakeredis.FakeRedis(decode_responses=True)
    syn = Syneidesis(
        strategy=_strategy(),
        top_k=5,
        publication_threshold=0.35,
        arm="competitive",
    )
    cycle, bus = _make_cycle(syn, ["soma.out", "topos.out"], client)
    try:
        await client.xadd("soma.out", _encode_event(_soma_event()), id="1760000000000-0")
        await client.xadd("topos.out", _encode_event(_topos_event()), id="1760000000000-0")
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
        assert ctx._members == [("soma", "soma.report", 0.9)]
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_candidates_are_ordered_by_source_first():
    client = fakeredis.FakeRedis(decode_responses=True)
    syn = FakeSyneidesis()
    cycle, bus = _make_cycle(syn, ["topos.out", "soma.out"], client)
    try:
        topos_event = Event(
            source="topos",
            type="topos.report",
            payload={"order": "third"},
            salience=0.5,
            timestamp=datetime(2026, 1, 1, 0, 0, 2, tzinfo=timezone.utc),
        )
        soma_first = Event(
            source="soma",
            type="soma.report",
            payload={"order": "first"},
            salience=0.5,
            timestamp=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        )
        soma_second = Event(
            source="soma",
            type="soma.report",
            payload={"order": "second"},
            salience=0.5,
            timestamp=datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc),
        )
        await client.xadd("topos.out", _encode_event(topos_event), id="1760000000000-0")
        await client.xadd("soma.out", _encode_event(soma_first), id="1760000000000-0")
        await client.xadd("soma.out", _encode_event(soma_second), id="1760000000000-1")
        await cycle.tick()
        assert len(syn.calls) == 1
        events = syn.calls[0]["events"]
        ids = [entry_id for entry_id, _ in events]
        assert ids == [
            "soma.out:1760000000000-0",
            "soma.out:1760000000000-1",
            "topos.out:1760000000000-0",
        ]
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_entry_id_orders_before_stream():
    client = fakeredis.FakeRedis(decode_responses=True)
    syn = FakeSyneidesis()
    cycle, bus = _make_cycle(syn, ["a.out", "b.out"], client)
    try:
        a_event = Event(
            source="soma",
            type="soma.report",
            payload={"stream": "a"},
            salience=0.5,
            timestamp=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        )
        b_event = Event(
            source="soma",
            type="soma.report",
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
    syn = Syneidesis(
        strategy=_strategy(),
        top_k=5,
        publication_threshold=0.35,
        **kwargs,
    )
    now = datetime.now(timezone.utc)
    ev1 = Event(
        source="soma",
        type="soma.report",
        payload={},
        salience=0.9,
        timestamp=now,
    )
    ev2 = Event(
        source="topos",
        type="topos.report",
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
    key = stream_entry_key("soma.out", "1760000000000-0")
    assert key == "soma.out:1760000000000-0"
    assert split_stream_entry_key(key) == ("soma.out", "1760000000000-0")
    assert split_stream_entry_key("1760000000000-0") == (None, "1760000000000-0")
