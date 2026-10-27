# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests that pin the order of the final sleep phase.

At the end of a sleep the developmental rest hold finishes first,
then housekeeping runs, and finally the affective reset happens.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.sleep import (
    FakeTrainer,
    Sleep,
    VoiceAlignmentConfig,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


class FakeEpisodicMemory:
    def __init__(self) -> None:
        self.consolidated = 0
        self.downscale_calls: list[float] = []
        self.replay_calls = 0

    async def consolidate_now(self) -> int:
        self.consolidated += 1
        return 0

    async def downscale(self, protect=()):
        protect = list(protect)
        self.downscale_calls.append(protect)
        return {"n_new": 0, "factor": 1.0, "protected": len(protect), "total_before": 0.0, "total_after": 0.0, "silent": 0}

    async def replay_now(self) -> list:
        self.replay_calls += 1
        return []


class FakeAffect:
    def __init__(self) -> None:
        self.resets = 0
        self.reset_at: float | None = None

    async def affective_reset(self) -> None:
        self.resets += 1
        self.reset_at = time.monotonic()


class RecordingAffect(FakeAffect):
    def __init__(self, events: list[tuple[str, float]]) -> None:
        super().__init__()
        self.events = events

    async def affective_reset(self) -> None:
        await super().affective_reset()
        self.events.append(("reset", time.monotonic()))


class FakeHousekeeper:
    def __init__(self, events: list[tuple[str, float]]) -> None:
        self.events = events
        self.calls = 0

    async def run(self, *, episodic_store_bytes=None):
        self.calls += 1
        self.events.append(("housekeeping", time.monotonic()))
        return {
            "stopped": "within_budget",
            "moved_files": 0,
            "pressure": 0.0,
            "terms": {"disk": 0.0, "memory": 0.0, "episodic": 0.0},
        }


class FakeEntityClock:
    def __init__(self, offset: float = 0.0) -> None:
        self.offset = offset

    def now(self) -> float:
        return time.monotonic() - self.offset


def _make_sleep(bus: AsyncBus, tmp_path: Path, **kwargs) -> Sleep:
    config = VoiceAlignmentConfig(
        intent_log_path=tmp_path / "intent.jsonl",
        adapter_output_dir=tmp_path / "adapters",
        enabled=False,
    )
    defaults = {
        "episodic_memory": FakeEpisodicMemory(),
        "affect": FakeAffect(),
        "trainer": FakeTrainer(),
        "voice_alignment_config": config,
    }
    defaults.update(kwargs)
    return Sleep(bus, **defaults)


async def test_developmental_rest_order_is_hold_then_housekeeping_then_reset(bus, tmp_path):
    events: list[tuple[str, float]] = []
    affect = RecordingAffect(events)
    housekeeper = FakeHousekeeper(events)

    sleep = _make_sleep(bus, tmp_path, affect=affect, developmental_rest_s=0.3)
    sleep._housekeeper = housekeeper

    original_hold = sleep._hold_developmental_rest

    async def wrapped_hold(*args, **kwargs) -> None:
        await original_hold(*args, **kwargs)
        events.append(("hold_end", time.monotonic()))

    sleep._hold_developmental_rest = wrapped_hold

    start = time.monotonic()
    await sleep.enter_sleep(trigger="state_cycle")

    names = [name for name, _ in events]
    assert names == ["hold_end", "housekeeping", "reset"]
    assert housekeeper.calls == 1

    housekeeping_ts = next(ts for name, ts in events if name == "housekeeping")
    assert housekeeping_ts - start >= 0.25


async def test_ordinary_sleep_order_is_housekeeping_then_reset_without_hold(bus, tmp_path):
    events: list[tuple[str, float]] = []
    affect = RecordingAffect(events)
    housekeeper = FakeHousekeeper(events)

    sleep = _make_sleep(bus, tmp_path, affect=affect)
    sleep._housekeeper = housekeeper

    await sleep.enter_sleep()

    names = [name for name, _ in events]
    assert names == ["housekeeping", "reset"]
    assert "hold_end" not in names
    assert housekeeper.calls == 1


async def test_cancel_during_hold_runs_reset_but_not_housekeeping(bus, tmp_path):
    events: list[tuple[str, float]] = []
    affect = RecordingAffect(events)
    housekeeper = FakeHousekeeper(events)

    sleep = _make_sleep(bus, tmp_path, affect=affect, developmental_rest_s=30.0)
    sleep._housekeeper = housekeeper

    task = asyncio.create_task(sleep.enter_sleep(trigger="state_cycle"))
    await asyncio.sleep(0.2)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert housekeeper.calls == 0
    assert [name for name, _ in events] == ["reset"]
