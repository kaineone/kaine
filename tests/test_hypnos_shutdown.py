# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for Hypnos.shutdown cleaning up the in-flight sleep and held tasks.
"""

import asyncio
import logging
from datetime import datetime, timezone

import pytest

import kaine.modules.hypnos.module as hypnos_module
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.modules.hypnos import FakeTrainer, Hypnos, VoiceAlignmentConfig


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


class RecordingThymos:
    def __init__(
        self,
        calls: list[str] | None = None,
        gate: asyncio.Event | None = None,
    ) -> None:
        self.calls = calls if calls is not None else []
        self.gate = gate
        self.resets = 0
        self.started = asyncio.Event()

    async def affective_reset(self) -> None:
        self.started.set()
        if self.gate is not None:
            await self.gate.wait()
        self.resets += 1
        self.calls.append("reset")


class RecordingMnemos:
    def __init__(
        self,
        calls: list[str],
        hang_in: str | None = None,
    ) -> None:
        self.calls = calls
        self.hang_in = hang_in
        self.entered = asyncio.Event()

    async def consolidate_now(self) -> int:
        self.calls.append("consolidate")
        if self.hang_in == "consolidate":
            self.entered.set()
            await asyncio.Event().wait()
        return 0

    def open_replay_window(self) -> None:
        self.calls.append("open")

    def close_replay_window(self) -> None:
        self.calls.append("close")

    async def replay_now(self) -> list:
        self.calls.append("replay")
        if self.hang_in == "replay":
            self.entered.set()
            await asyncio.Event().wait()
        return []

    async def downscale(self, protect=()):
        self.calls.append("downscale")
        return {"n_new": 0, "factor": 1.0, "protected": len(protect), "total_before": 0.0, "total_after": 0.0, "silent": 0}

    async def select_cross_period_traces(
        self,
        *,
        periods: int,
        per_period: int,
    ) -> dict:
        self.calls.append("associative")
        return {}


def _make_hypnos(bus, tmp_path, *, mnemos, thymos, associative=False):
    return Hypnos(
        bus,
        mnemos=mnemos,
        thymos=thymos,
        trainer=FakeTrainer(),
        voice_alignment_config=VoiceAlignmentConfig(
            intent_log_path=tmp_path / "intent.jsonl",
            adapter_output_dir=tmp_path / "adapters",
            enabled=False,
        ),
        perception_desired_path=tmp_path / "perception_desired.json",
        associative_replay_enabled=associative,
    )


async def _completed_events(bus) -> list[dict]:
    entries = await bus.read("hypnos.out", last_id="0")
    return [e.payload for _, e in entries if e.type == "hypnos.sleep.completed"]


@pytest.mark.asyncio
async def test_shutdown_during_a_sleep_resets_and_reports(bus, tmp_path):
    calls = []
    mnemos = RecordingMnemos(calls, hang_in="replay")
    thymos = RecordingThymos()
    hypnos = _make_hypnos(bus, tmp_path, mnemos=mnemos, thymos=thymos)

    await hypnos.initialize()
    await bus.publish(
        Event(
            source="soma",
            type="soma.fatigue",
            payload={"crossed": True},
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        )
    )
    await asyncio.wait_for(mnemos.entered.wait(), 5)
    await asyncio.wait_for(hypnos.shutdown(), 10)

    completed = await _completed_events(bus)
    assert thymos.resets == 1
    assert hypnos._sleep_task.done()
    assert not hypnos._shielded_tasks
    assert "close" in calls
    assert len(completed) == 1
    assert completed[0]["aborted"] is True
    assert completed[0]["reason"] == "CancelledError"


@pytest.mark.asyncio
async def test_shutdown_waits_for_a_held_reset(bus, tmp_path):
    gate = asyncio.Event()
    thymos = RecordingThymos(gate=gate)
    mnemos = RecordingMnemos([])
    hypnos = _make_hypnos(bus, tmp_path, mnemos=mnemos, thymos=thymos)
    await hypnos.initialize()

    entered = asyncio.Event()

    async def fake_run_voice_alignment():
        entered.set()
        await asyncio.Event().wait()

    hypnos._run_voice_alignment = fake_run_voice_alignment
    hypnos._sleep_pending = True
    hypnos._sleep_task = asyncio.create_task(
        hypnos._interval_triggered_enter_sleep(),
        name="hypnos-interval-sleep",
    )

    await asyncio.wait_for(entered.wait(), 5)
    hypnos._sleep_task.cancel()
    await asyncio.wait_for(thymos.started.wait(), 5)
    asyncio.get_running_loop().call_later(0.1, gate.set)
    await asyncio.wait_for(hypnos.shutdown(), 10)

    assert thymos.resets == 1
    assert not hypnos._shielded_tasks


@pytest.mark.asyncio
async def test_shutdown_wait_is_bounded(bus, tmp_path, monkeypatch, caplog):
    gate = asyncio.Event()
    thymos = RecordingThymos(gate=gate)
    mnemos = RecordingMnemos([])
    hypnos = _make_hypnos(bus, tmp_path, mnemos=mnemos, thymos=thymos)
    await hypnos.initialize()

    entered = asyncio.Event()

    async def fake_run_voice_alignment():
        entered.set()
        await asyncio.Event().wait()

    hypnos._run_voice_alignment = fake_run_voice_alignment
    monkeypatch.setattr(hypnos_module, "_SHUTDOWN_WAIT_S", 0.1)
    hypnos._sleep_pending = True
    hypnos._sleep_task = asyncio.create_task(
        hypnos._interval_triggered_enter_sleep(),
        name="hypnos-interval-sleep",
    )

    await asyncio.wait_for(entered.wait(), 5)
    hypnos._sleep_task.cancel()
    await asyncio.wait_for(thymos.started.wait(), 5)

    loop = asyncio.get_running_loop()
    start = loop.time()
    with caplog.at_level(logging.WARNING, logger="kaine.modules.hypnos.module"):
        await asyncio.wait_for(hypnos.shutdown(), 10)
    duration = loop.time() - start

    assert duration < 2.0
    assert thymos.resets == 0
    assert "pending" in caplog.text

    gate.set()
    await asyncio.gather(*list(hypnos._shielded_tasks), return_exceptions=True)
    assert thymos.resets == 1


@pytest.mark.asyncio
async def test_shutdown_without_a_sleep(bus, tmp_path):
    thymos = RecordingThymos()
    mnemos = RecordingMnemos([])
    hypnos = _make_hypnos(bus, tmp_path, mnemos=mnemos, thymos=thymos)
    await hypnos.initialize()
    await asyncio.wait_for(hypnos.shutdown(), 10)

    assert thymos.resets == 0
    assert not await _completed_events(bus)
