# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Workspace-following evaluation observers (trajectory, attribution).

Guards the bug found live 2026-06-03: these observers read `workspace.broadcast`
via the standard Event decode, which rejects the broadcast's `{snapshot: <json>}`
shape, so they silently recorded nothing. They must consume the broadcast via
the canonical `subscribe_workspace` decoded-snapshot path.
"""
import asyncio

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.evaluation.attribution import AttributionRecorder
from kaine.evaluation.trajectory import TrajectoryRecorder


class FakeSink:
    def __init__(self):
        self.rows = []

    async def write(self, entry):
        self.rows.append(entry)


class FakeWorkspaceBus:
    """Yields canned (entry_id, snapshot_dict) pairs via subscribe_workspace,
    then ends — mirroring the real bus's decoded output without a server."""

    def __init__(self, broadcasts):
        self._broadcasts = broadcasts

    async def subscribe_workspace(self, last_id="$", count=32, poll_interval_s=0.05):
        for entry_id, payload in self._broadcasts:
            yield entry_id, payload


def _snapshot(tick, sources, salience=None):
    return {
        "tick_index": tick,
        "is_experiential": True,
        "inhibited": False,
        "salience_scores": salience or {s: 0.5 for s in sources},
        "selected": [{"source": s, "type": f"{s}.report", "entry_id": f"{tick}-{i}"}
                     for i, s in enumerate(sources)],
        "metadata": {},
    }


async def _drain(observer, sink, n_expected, timeout=2.0):
    await observer.start()
    waited = 0.0
    while len(sink.rows) < n_expected and waited < timeout:
        await asyncio.sleep(0.01)
        waited += 0.01
    await observer.stop()


# ---- trajectory -------------------------------------------------------------

@pytest.mark.asyncio
async def test_trajectory_writes_one_row_per_broadcast():
    broadcasts = [
        ("1-0", _snapshot(1, ["soma", "thymos"])),
        ("2-0", _snapshot(2, ["chronos"])),
        ("3-0", _snapshot(3, ["mnemos", "nous", "soma"])),
    ]
    sink = FakeSink()
    rec = TrajectoryRecorder(FakeWorkspaceBus(broadcasts), sink)
    await _drain(rec, sink, n_expected=3)
    assert len(sink.rows) == 3
    assert [r["tick_index"] for r in sink.rows] == [1, 2, 3]
    # The decoded snapshot's selected/salience made it into the row.
    assert sink.rows[2]["salience_scores"] == {"mnemos": 0.5, "nous": 0.5, "soma": 0.5}
    assert {item["source"] for item in sink.rows[0]["selected"]} == {"soma", "thymos"}


@pytest.mark.asyncio
async def test_trajectory_includes_thymos_state_when_provided():
    sink = FakeSink()
    rec = TrajectoryRecorder(
        FakeWorkspaceBus([("1-0", _snapshot(1, ["soma"]))]),
        sink,
        thymos_state_provider=lambda: {"valence": 0.2, "arousal": 0.4},
    )
    await _drain(rec, sink, n_expected=1)
    assert sink.rows[0]["thymos_state"] == {"valence": 0.2, "arousal": 0.4}


# ---- attribution ------------------------------------------------------------

@pytest.mark.asyncio
async def test_attribution_tallies_sources_and_flushes_on_stop():
    broadcasts = [
        ("1-0", _snapshot(1, ["soma", "thymos"])),
        ("2-0", _snapshot(2, ["soma"])),
        ("3-0", _snapshot(3, ["soma", "nous"])),
    ]
    sink = FakeSink()
    rec = AttributionRecorder(FakeWorkspaceBus(broadcasts), sink)
    await rec.start()
    for _ in range(200):
        await asyncio.sleep(0.01)
        if rec.running_total.get("soma") == 3:
            break
    assert rec.running_total == {"soma": 3, "thymos": 1, "nous": 1}
    await rec.stop()  # flushes the partial current hour
    assert sink.rows, "stop() should flush a partial-hour rollup"
    assert sink.rows[-1]["counts"].get("soma") == 3
    assert sink.rows[-1].get("partial") is True


# ---- integration: real bus, the exact broadcast shape -----------------------

@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


@pytest.mark.asyncio
async def test_trajectory_records_real_broadcast_and_event_decode_would_not(bus):
    # Publish exactly as Syneidesis does — {snapshot:<json>,...}.
    await bus.publish_workspace(_snapshot(7, ["soma", "eidolon"]), source="syneidesis")
    sink = FakeSink()
    rec = TrajectoryRecorder(bus, sink)
    rec._start_id = "0"  # read the backlog deterministically (no $-resolve race)
    await rec.start()
    for _ in range(200):
        await asyncio.sleep(0.01)
        if sink.rows:
            break
    await rec.stop()
    assert len(sink.rows) == 1
    assert sink.rows[0]["tick_index"] == 7

    # Regression guard: the entry IS in the stream...
    raw_len = await bus._client.xlen("workspace.broadcast")
    assert raw_len == 1
    # ...but the standard Event decode (what the observer used to use) rejects
    # the broadcast shape outright (no type/salience), recording nothing — which
    # is exactly why workspace observers must use subscribe_workspace.
    entries, _ = await bus.read_entries("workspace.broadcast", last_id="0")
    assert entries == []


@pytest.mark.asyncio
async def test_trajectory_records_multiple_sequential_broadcasts(bus):
    sink = FakeSink()
    rec = TrajectoryRecorder(bus, sink)
    rec._start_id = "0"
    await rec.start()
    for tick in (10, 11, 12):
        await bus.publish_workspace(_snapshot(tick, ["soma"]), source="syneidesis")
    for _ in range(300):
        await asyncio.sleep(0.01)
        if len(sink.rows) >= 3:
            break
    await rec.stop()
    assert [r["tick_index"] for r in sink.rows] == [10, 11, 12]


@pytest.mark.asyncio
async def test_subscribe_workspace_skips_a_corrupt_broadcast(bus):
    # A truncated/corrupt snapshot field must not kill the subscription.
    await bus._client.xadd(
        "workspace.broadcast",
        {"snapshot": "{not valid json", "timestamp": "t", "source": "syneidesis"},
    )
    await bus.publish_workspace(_snapshot(5, ["nous"]), source="syneidesis")
    sink = FakeSink()
    rec = TrajectoryRecorder(bus, sink)
    rec._start_id = "0"
    await rec.start()
    for _ in range(200):
        await asyncio.sleep(0.01)
        if sink.rows:
            break
    await rec.stop()
    # The good broadcast after the corrupt one was still recorded.
    assert [r["tick_index"] for r in sink.rows] == [5]


# ---- additional coverage (from review) --------------------------------------

class IdleWorkspaceBus:
    """subscribe_workspace that never yields and never ends — exercises the
    stop-while-idle race in WorkspaceSubscriberObserver._run."""

    async def subscribe_workspace(self, last_id="$", count=32, poll_interval_s=0.05):
        while True:
            await asyncio.sleep(0.005)
            if False:  # pragma: no cover
                yield


@pytest.mark.asyncio
async def test_trajectory_records_row_when_thymos_provider_raises():
    def _boom():
        raise RuntimeError("boom")

    sink = FakeSink()
    rec = TrajectoryRecorder(
        FakeWorkspaceBus([("1-0", _snapshot(1, ["soma"]))]),
        sink,
        thymos_state_provider=_boom,
    )
    await _drain(rec, sink, n_expected=1)
    # Fail-soft: the row is still written, with thymos_state None.
    assert len(sink.rows) == 1
    assert sink.rows[0]["thymos_state"] is None
    assert sink.rows[0]["tick_index"] == 1


@pytest.mark.asyncio
async def test_attribution_stop_while_idle_is_prompt_and_flushless():
    sink = FakeSink()
    rec = AttributionRecorder(IdleWorkspaceBus(), sink)
    await rec.start()
    await asyncio.sleep(0.02)
    # Must stop promptly (guards the 5s-cancel regression) and flush nothing.
    await asyncio.wait_for(rec.stop(), timeout=2.0)
    assert sink.rows == []
    assert rec.running_total == {}


@pytest.mark.asyncio
async def test_attribution_skips_non_dict_selected_items():
    broadcasts = [("1-0", {"selected": [None, "not-a-dict", {"source": "soma"}]})]
    sink = FakeSink()
    rec = AttributionRecorder(FakeWorkspaceBus(broadcasts), sink)
    await rec.start()
    for _ in range(200):
        await asyncio.sleep(0.01)
        if rec.running_total.get("soma") == 1:
            break
    await rec.stop()
    assert rec.running_total == {"soma": 1}  # non-dicts silently discarded


@pytest.mark.asyncio
async def test_attribution_flushes_non_partial_row_on_hour_boundary(monkeypatch):
    import kaine.evaluation.attribution as attr_mod
    from datetime import datetime, timezone

    times = [
        datetime(2026, 6, 3, 10, 30, tzinfo=timezone.utc),
        datetime(2026, 6, 3, 11, 5, tzinfo=timezone.utc),
    ]
    idx = [0]

    class FakeDateTime:
        @staticmethod
        def now(tz=None):
            return times[idx[0]]

    monkeypatch.setattr(attr_mod, "datetime", FakeDateTime)
    sink = FakeSink()
    rec = AttributionRecorder(FakeWorkspaceBus([]), sink)

    await rec.handle("1-0", {"selected": [{"source": "soma"}]})  # hour A
    assert rec.current_hour_counts == {"soma": 1}
    assert sink.rows == []

    idx[0] = 1  # cross the hour boundary
    await rec.handle("2-0", {"selected": [{"source": "thymos"}]})  # hour B
    assert len(sink.rows) == 1
    assert sink.rows[0]["hour"] == "2026-06-03T10"
    assert sink.rows[0]["counts"] == {"soma": 1}
    assert "partial" not in sink.rows[0]  # mid-session flush is final, not partial
    assert rec.current_hour_counts == {"thymos": 1}
    assert rec.running_total == {"soma": 1, "thymos": 1}
