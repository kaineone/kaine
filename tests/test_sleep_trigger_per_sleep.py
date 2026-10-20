# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Each sleep records the trigger that started it (change sleep-trigger-per-sleep).

Covers:
- a fatigue sleep followed by a backstop sleep records ``fatigue`` then
  ``backstop`` (the old module-level flag made both read as fatigue)
- both maintenance-request paths record their own trigger and are not fatigue
- ``sleep.sleep.started`` and the aborted completed event carry the trigger
- a trigger that loses the start race leaves the running sleep's trigger alone
- a direct ``enter_sleep()`` records a null trigger
- the research event observer keeps ``trigger`` on both sleep events

The bus is seeded with fakeredis so no Redis is needed.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import validate_event
from kaine.evaluation.observers.research_event_observer import ResearchEventObserver
from kaine.modules.sleep import (
    FakeTrainer,
    RestScheduler,
    Sleep,
    VoiceAlignmentConfig,
)
from kaine.modules.sleep.module import SleepBusyError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


class FakeEpisodicMemory:
    def __init__(self) -> None:
        self.gate: asyncio.Event | None = None
        self.entered = asyncio.Event()

    async def consolidate_now(self) -> int:
        return 0

    async def downscale(self, protect=()):
        protect = list(protect)
        return {
            "n_new": 0,
            "factor": 1.0,
            "protected": len(protect),
            "total_before": 0.0,
            "total_after": 0.0,
            "silent": 0,
        }

    async def replay_now(self) -> list:
        if self.gate is not None:
            self.entered.set()
            await self.gate.wait()
        return []


class FakeAffect:
    async def affective_reset(self) -> None:
        return None


def _make_sleep(bus: AsyncBus, tmp_path: Path, **kwargs) -> Sleep:
    config = VoiceAlignmentConfig(
        intent_log_path=tmp_path / "intent.jsonl",
        adapter_output_dir=tmp_path / "adapters",
        enabled=False,
    )
    kwargs.setdefault("episodic_memory", FakeEpisodicMemory())
    return Sleep(
        bus,
        affect=FakeAffect(),
        trainer=FakeTrainer(),
        voice_alignment_config=config,
        **kwargs,
    )


async def _publish(bus: AsyncBus, source: str, type_: str, payload: dict) -> None:
    await bus.publish(
        validate_event(
            source=source,
            type=type_,
            payload=payload,
            salience=0.7,
            timestamp=datetime.now(timezone.utc),
        )
    )


async def _events(bus: AsyncBus, type_: str) -> list[dict]:
    entries = await bus.read("sleep.out", last_id="0")
    return [e.payload for _, e in entries if e.type == type_]


async def _wait_for_completed(bus: AsyncBus, count: int, timeout: float = 5.0) -> list[dict]:
    async def _poll() -> list[dict]:
        while True:
            found = await _events(bus, "sleep.sleep.completed")
            if len(found) >= count:
                return found
            await asyncio.sleep(0.02)

    return await asyncio.wait_for(_poll(), timeout)


async def _settle(sleep: Sleep) -> None:
    task = sleep._sleep_task
    assert task is not None, "a sleep task must have been started"
    await asyncio.wait_for(asyncio.shield(task), 5.0)


# ---------------------------------------------------------------------------
# a. A fatigue sleep, then a backstop sleep
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fatigue_sleep_then_backstop_sleep_record_their_own_trigger(
    bus: AsyncBus, tmp_path: Path
):
    sleep = _make_sleep(bus, tmp_path)
    await sleep.initialize()
    try:
        await _publish(
            bus,
            "interoception",
            "interoception.fatigue",
            {"value": 105.0, "threshold": 100.0, "crossed": True},
        )
        first = (await _wait_for_completed(bus, 1))[0]
        await _settle(sleep)

        # The maintenance poll reads the scheduler; make the next sleep due.
        sleep._scheduler = RestScheduler(interval_seconds=0.001, max_deferral_seconds=0.0)
        second = (await _wait_for_completed(bus, 2))[1]
    finally:
        await sleep.shutdown()

    assert first["trigger"] == "fatigue"
    assert first["fatigue_triggered"] is True
    assert second["trigger"] == "backstop"
    assert second["fatigue_triggered"] is False


# ---------------------------------------------------------------------------
# b. Maintenance requests are not fatigue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source", "type_", "expected"),
    [
        ("interoception", "interoception.regulation", "maintenance_request"),
        ("affect", "affect.regulation", "affect_regulation"),
    ],
)
async def test_maintenance_requests_record_their_own_trigger(
    bus: AsyncBus, tmp_path: Path, source: str, type_: str, expected: str
):
    sleep = _make_sleep(bus, tmp_path)
    await sleep.initialize()
    try:
        await _publish(
            bus,
            source,
            type_,
            {"action": "request_maintenance", "reason": "stress", "severity": 3},
        )
        completed = (await _wait_for_completed(bus, 1))[0]
        await _settle(sleep)
    finally:
        await sleep.shutdown()

    assert completed["trigger"] == expected
    assert completed["fatigue_triggered"] is False


# ---------------------------------------------------------------------------
# c. The started event carries the trigger
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_started_event_carries_the_trigger(bus: AsyncBus, tmp_path: Path):
    sleep = _make_sleep(bus, tmp_path)
    await sleep.enter_sleep(trigger="requested")
    await sleep.enter_sleep(trigger="backstop")

    started = await _events(bus, "sleep.sleep.started")
    assert [p["trigger"] for p in started] == ["requested", "backstop"]
    assert [p["sleep_index"] for p in started] == [1, 2]


@pytest.mark.asyncio
async def test_start_site_trigger_reaches_the_started_event(bus: AsyncBus, tmp_path: Path):
    sleep = _make_sleep(bus, tmp_path)
    await sleep.initialize()
    try:
        await sleep._start_maintenance_sleep("maintenance_request")
        await _settle(sleep)
    finally:
        await sleep.shutdown()

    started = await _events(bus, "sleep.sleep.started")
    assert len(started) == 1
    assert started[0]["trigger"] == "maintenance_request"


# ---------------------------------------------------------------------------
# d. The aborted completed event carries the trigger
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aborted_completed_event_carries_the_trigger(bus: AsyncBus, tmp_path: Path):
    sleep = _make_sleep(bus, tmp_path)

    async def _boom(trigger=None):
        raise RuntimeError("phase failure")

    sleep._run_pipeline_inner = _boom

    with pytest.raises(RuntimeError):
        await sleep.enter_sleep(trigger="backstop")
    with pytest.raises(RuntimeError):
        await sleep.enter_sleep()

    completed = await _events(bus, "sleep.sleep.completed")
    assert len(completed) == 2
    assert all(p["aborted"] is True for p in completed)
    assert completed[0]["trigger"] == "backstop"
    assert "trigger" in completed[1] and completed[1]["trigger"] is None


@pytest.mark.asyncio
async def test_cancelled_sleep_reports_its_trigger(bus: AsyncBus, tmp_path: Path):
    memory = FakeEpisodicMemory()
    memory.gate = asyncio.Event()
    sleep = _make_sleep(bus, tmp_path, episodic_memory=memory)

    task = asyncio.create_task(sleep.enter_sleep(trigger="fatigue"))
    await asyncio.wait_for(memory.entered.wait(), 5.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    completed = await _events(bus, "sleep.sleep.completed")
    assert len(completed) == 1
    assert completed[0]["aborted"] is True
    assert completed[0]["trigger"] == "fatigue"


# ---------------------------------------------------------------------------
# e. A losing second trigger leaves the running sleep alone
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_losing_trigger_leaves_the_running_sleeps_trigger(bus: AsyncBus, tmp_path: Path):
    memory = FakeEpisodicMemory()
    memory.gate = asyncio.Event()
    sleep = _make_sleep(bus, tmp_path, episodic_memory=memory)
    await sleep.initialize()
    try:
        await sleep._start_maintenance_sleep("fatigue")
        await asyncio.wait_for(memory.entered.wait(), 5.0)

        # Loses the pending/lock guard: no second sleep is started.
        await sleep._start_maintenance_sleep("maintenance_request")
        await sleep._start_maintenance_sleep("affect_regulation")
        # Reaches enter_sleep directly and loses on the lock.
        with pytest.raises(SleepBusyError):
            await sleep.enter_sleep(trigger="backstop")

        memory.gate.set()
        await _settle(sleep)
    finally:
        await sleep.shutdown()

    started = await _events(bus, "sleep.sleep.started")
    completed = await _events(bus, "sleep.sleep.completed")
    assert len(started) == 1 and len(completed) == 1
    assert started[0]["trigger"] == "fatigue"
    assert completed[0]["trigger"] == "fatigue"
    assert completed[0]["fatigue_triggered"] is True


# ---------------------------------------------------------------------------
# f. A direct call records a null trigger
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_direct_enter_sleep_records_a_null_trigger(bus: AsyncBus, tmp_path: Path):
    sleep = _make_sleep(bus, tmp_path)
    summary = await sleep.enter_sleep()

    assert "trigger" in summary and summary["trigger"] is None
    assert summary["fatigue_triggered"] is False
    started = await _events(bus, "sleep.sleep.started")
    assert "trigger" in started[0] and started[0]["trigger"] is None
    completed = await _events(bus, "sleep.sleep.completed")
    assert "trigger" in completed[0] and completed[0]["trigger"] is None
    assert completed[0]["fatigue_triggered"] is False


@pytest.mark.asyncio
async def test_developmental_rest_keeps_its_rest_seconds(bus: AsyncBus, tmp_path: Path):
    sleep = _make_sleep(bus, tmp_path)
    sleep._developmental_rest_s = 0.0
    summary = await sleep.enter_sleep(trigger="developmental_rest")

    assert summary["trigger"] == "developmental_rest"
    assert summary["fatigue_triggered"] is False
    assert "rest_seconds" in summary


# ---------------------------------------------------------------------------
# g. The research event observer keeps the trigger
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_research_observer_keeps_trigger_on_both_sleep_events(
    bus: AsyncBus, tmp_path: Path
):
    sleep = _make_sleep(bus, tmp_path)
    await sleep.enter_sleep(trigger="backstop")

    entries = await bus.read("sleep.out", last_id="0")
    observer = ResearchEventObserver(bus, sink=None)  # type: ignore[arg-type]
    records = {
        e.type: observer._build_record(e)
        for _, e in entries
        if e.type in ("sleep.sleep.started", "sleep.sleep.completed")
    }

    assert records["sleep.sleep.started"]["trigger"] == "backstop"
    assert records["sleep.sleep.completed"]["trigger"] == "backstop"


# ---------------------------------------------------------------------------
# The faithful narration names the trigger
# ---------------------------------------------------------------------------


def test_faithful_narration_names_the_trigger():
    from kaine.faithful.templates import TEMPLATES

    render = TEMPLATES[("sleep", "sleep.sleep.completed")]
    base = {"phases": [{"success": True}], "total_elapsed_ms": 12.0}

    named = render({**base, "trigger": "backstop", "fatigue_triggered": False})
    assert "trigger backstop" in named
    assert "fatigue-triggered" not in named

    assert "trigger none" not in render({**base, "trigger": None, "fatigue_triggered": False})
    # Older records carry only the flag.
    assert "fatigue-triggered" in render({**base, "fatigue_triggered": True})
