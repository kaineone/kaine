# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Regression tests for review fixes to developmental rest handling."""

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


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


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
        self.reset_at: float | None = None

    async def affective_reset(self) -> None:
        self.resets += 1
        self.reset_at = time.monotonic()


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


async def _wait_for_started(
    bus: AsyncBus, trigger: str | None = None, timeout: float = 2.0
) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        entries = await bus.read("sleep.out", last_id="0", count=1000)
        for _, event in entries:
            if event.type == "sleep.sleep.started":
                if trigger is None or event.payload.get("trigger") == trigger:
                    return event.payload
        if asyncio.get_running_loop().time() >= deadline:
            raise asyncio.TimeoutError("no sleep.sleep.started event")
        await asyncio.sleep(0.02)


async def _wait_for_aborted_completed(
    bus: AsyncBus, timeout: float = 2.0
) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        entries = await bus.read("sleep.out", last_id="0", count=1000)
        for _, event in entries:
            if event.type == "sleep.sleep.completed" and event.payload.get("aborted"):
                return event.payload
        if asyncio.get_running_loop().time() >= deadline:
            raise asyncio.TimeoutError("no aborted sleep.sleep.completed event")
        await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_aborted_developmental_rest_includes_trigger_and_rest_seconds(
    bus, tmp_path: Path
):
    sleep = _make_sleep(
        bus,
        tmp_path,
        developmental_rest_s=30.0,
        entity_clock=FakeEntityClock(),
    )
    task = asyncio.create_task(
        sleep.enter_sleep(trigger="state_cycle")
    )
    await _wait_for_started(bus, trigger="state_cycle")
    await asyncio.sleep(0.05)
    task.cancel()
    (outcome,) = await asyncio.gather(task, return_exceptions=True)
    assert isinstance(outcome, asyncio.CancelledError)

    payload = await _wait_for_aborted_completed(bus)
    assert payload["aborted"] is True
    assert payload.get("trigger") == "state_cycle"
    assert payload.get("rest_seconds") == 30.0


@pytest.mark.asyncio
async def test_aborted_ordinary_sleep_has_null_trigger_and_no_rest_seconds(
    bus, tmp_path: Path
):
    sleep = _make_sleep(bus, tmp_path)

    async def _slow_phase(*args, **kwargs):
        await asyncio.sleep(30)

    sleep._run_voice_alignment = _slow_phase

    task = asyncio.create_task(sleep.enter_sleep())
    await _wait_for_started(bus)
    await asyncio.sleep(0.05)
    task.cancel()
    (outcome,) = await asyncio.gather(task, return_exceptions=True)
    assert isinstance(outcome, asyncio.CancelledError)

    payload = await _wait_for_aborted_completed(bus)
    assert payload["aborted"] is True
    assert "trigger" in payload and payload["trigger"] is None
    assert "rest_seconds" not in payload
