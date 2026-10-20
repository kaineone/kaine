# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for sleep housekeeping integration (paper 3.5 and A.5)."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Optional

import pytest

import kaine.storage
from kaine.boot.factories.sleep import make_sleep
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.sleep import FakeTrainer, Sleep, VoiceAlignmentConfig
from kaine.modules.sleep.housekeeping import (
    Housekeeper,
    HousekeepingConfig,
    HousekeepingRefused,
    bus_memory_bytes,
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
        return {
            "n_new": 0,
            "factor": 1.0,
            "protected": len(protect),
            "total_before": 0.0,
            "total_after": 0.0,
            "silent": 0,
        }

    async def replay_now(self) -> list:
        self.replay_calls += 1
        return []


class FakeAffect:
    def __init__(self) -> None:
        self.resets = 0
        self.reset_time: Optional[float] = None

    async def affective_reset(self) -> None:
        self.resets += 1
        self.reset_time = time.monotonic()


class FakeHousekeeper:
    def __init__(self) -> None:
        self.ran = 0
        self.call_time: Optional[float] = None
        self.episodic_store_bytes: Optional[int] = None

    async def run(self, *, episodic_store_bytes=None):
        self.ran += 1
        self.call_time = time.monotonic()
        self.episodic_store_bytes = episodic_store_bytes
        return {"stopped": "within_budget", "moved_files": 0, "pressure": 0.0}


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


async def test_housekeeper_runs_once_before_affective_reset(bus, tmp_path):
    housekeeper = FakeHousekeeper()
    affect = FakeAffect()
    sleep = _make_sleep(bus, tmp_path, housekeeper=housekeeper, affect=affect)
    summary = await sleep.enter_sleep()
    assert housekeeper.ran == 1
    assert affect.resets == 1
    assert housekeeper.call_time is not None
    assert housekeeper.call_time < affect.reset_time
    assert summary["housekeeping"] == {
        "stopped": "within_budget",
        "moved_files": 0,
        "pressure": 0.0,
    }
    await sleep.shutdown()


async def test_housekeeper_failure_continues_and_runs_reset(bus, tmp_path):
    class FailingHousekeeper:
        async def run(self, *, episodic_store_bytes=None):
            raise RuntimeError("housekeeping failed")

    sleep = _make_sleep(bus, tmp_path, housekeeper=FailingHousekeeper())
    summary = await sleep.enter_sleep()
    assert summary["housekeeping"] == {"failed": True}
    await sleep.shutdown()


async def test_no_housekeeper_omits_summary_key(bus, tmp_path):
    sleep = _make_sleep(bus, tmp_path)
    summary = await sleep.enter_sleep()
    assert "housekeeping" not in summary
    await sleep.shutdown()


async def test_cancel_during_phase_one_skips_housekeeper(bus, tmp_path):
    class SlowEpisodicMemory(FakeEpisodicMemory):
        async def consolidate_now(self) -> int:
            await asyncio.sleep(5)
            return 0

    housekeeper = FakeHousekeeper()
    sleep = _make_sleep(
        bus, tmp_path, episodic_memory=SlowEpisodicMemory(), housekeeper=housekeeper
    )
    task = asyncio.create_task(sleep.enter_sleep())
    await asyncio.sleep(0.2)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert housekeeper.ran == 0
    await sleep.shutdown()


async def test_real_housekeeper_archives_closed_files(bus, tmp_path):
    prev_root = kaine.storage.data_root()
    kaine.storage.set_data_root(tmp_path)
    try:
        events_dir = tmp_path / "data" / "evaluation" / "research_events"
        events_dir.mkdir(parents=True)
        today = time.strftime("%Y-%m-%d", time.gmtime())
        (events_dir / f"events-{today}.jsonl").write_text("today\n")
        (events_dir / "events-2024-01-01.jsonl").write_text("old1\n")
        (events_dir / "events-2024-01-02.jsonl").write_text("old2\n")

        hk_config = HousekeepingConfig(
            enabled=True,
            disk_budget_bytes=1,
            archive_dir=str(tmp_path / "archive"),
        )
        housekeeper = Housekeeper(
            hk_config, memory_reader=lambda: bus_memory_bytes(bus.client)
        )
        sleep = _make_sleep(bus, tmp_path, housekeeper=housekeeper)
        summary = await sleep.enter_sleep()

        assert summary["housekeeping"]["moved_files"] == 2
        assert not (events_dir / "events-2024-01-01.jsonl").exists()
        assert not (events_dir / "events-2024-01-02.jsonl").exists()
        assert (events_dir / f"events-{today}.jsonl").exists()
        assert (
            tmp_path / "archive" / "evaluation" / "research_events" / "events-2024-01-01.jsonl"
        ).exists()
        assert (
            tmp_path / "archive" / "evaluation" / "research_events" / "events-2024-01-02.jsonl"
        ).exists()
    finally:
        kaine.storage.set_data_root(prev_root)
    await sleep.shutdown()


async def test_make_sleep_disabled_housekeeper_none(bus, tmp_path):
    sleep = make_sleep(bus, {"housekeeping": {"enabled": False}})
    assert sleep._housekeeper is None


async def test_make_sleep_default_includes_housekeeper(bus, tmp_path):
    sleep = make_sleep(bus, {})
    assert isinstance(sleep._housekeeper, Housekeeper)


async def test_make_sleep_unknown_housekeeping_key_raises(bus, tmp_path):
    with pytest.raises(ValueError):
        make_sleep(bus, {"housekeeping": {"bogus": 1}})


async def test_make_sleep_archive_inside_root_raises(bus, tmp_path):
    prev_root = kaine.storage.data_root()
    kaine.storage.set_data_root(tmp_path)
    try:
        with pytest.raises(HousekeepingRefused):
            make_sleep(
                bus,
                {"housekeeping": {"archive_dir": str(tmp_path / "data" / "evaluation")}},
            )
    finally:
        kaine.storage.set_data_root(prev_root)
