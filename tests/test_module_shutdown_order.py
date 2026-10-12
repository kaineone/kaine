# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for module shutdown order and early Hypnos shutdown.
"""

import asyncio
import types

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.__main__ import _shutdown_modules
from kaine.cycle.spot import Spot
from kaine.modules.hypnos import FakeTrainer, Hypnos, VoiceAlignmentConfig
from kaine.modules.registry import shutdown_order


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


class FakeThymos:
    name = "thymos"

    def __init__(self) -> None:
        self.down = False
        self.reset_while_up = None

    async def shutdown(self) -> None:
        self.down = True

    async def affective_reset(self) -> None:
        self.reset_while_up = not self.down


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


def test_shutdown_order_puts_hypnos_first():
    a = types.SimpleNamespace(name="a")
    hypnos = types.SimpleNamespace(name="hypnos")
    b = types.SimpleNamespace(name="b")
    assert shutdown_order([a, hypnos, b]) == [hypnos, a, b]
    assert shutdown_order([a, b]) == [a, b]


async def test_cycle_shuts_hypnos_down_while_thymos_is_up(bus, tmp_path):
    """Sleep shutdown calls affective_reset while Affect is still up."""
    calls: list[str] = []
    mnemos = RecordingMnemos(calls, hang_in="replay")
    thymos = FakeThymos()
    hypnos = _make_hypnos(bus, tmp_path, mnemos=mnemos, thymos=thymos)
    await hypnos.initialize()
    hypnos._sleep_pending = True
    hypnos._sleep_task = asyncio.create_task(hypnos._interval_triggered_enter_sleep())
    await asyncio.wait_for(mnemos.entered.wait(), timeout=10)
    await asyncio.wait_for(_shutdown_modules([thymos, hypnos]), timeout=10)
    assert thymos.reset_while_up is True
    assert thymos.down is True


async def test_spot_shutdown_all_shuts_hypnos_down_first():
    """Supervisor shuts Sleep down before the other modules."""
    order: list[str] = []

    async def record_shutdown(name: str) -> None:
        order.append(name)

    a = types.SimpleNamespace(name="a", shutdown=lambda: record_shutdown("a"))
    b = types.SimpleNamespace(name="b", shutdown=lambda: record_shutdown("b"))
    hypnos = types.SimpleNamespace(name="hypnos", shutdown=lambda: record_shutdown("hypnos"))
    registry = types.SimpleNamespace(all_modules=lambda: [a, b, hypnos])
    await Spot._shutdown_all(types.SimpleNamespace(_registry=registry))
    assert order == ["hypnos", "a", "b"]
