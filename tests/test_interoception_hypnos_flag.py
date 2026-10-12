# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the interoception module's _in_hypnos flag and weight-freeze behaviour.

Spec requirements (spec.md):
- _in_hypnos is False at start.
- Becomes True on receipt of hypnos.sleep.started.
- Forward-model weights are frozen while _in_hypnos is True.
- Becomes False on receipt of hypnos.sleep.completed.
- Adaptation resumes after sleep.completed.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.interoception.module import Interoception


class FakeMetricsReader:
    def __init__(self, metrics: dict[str, float] | None = None) -> None:
        self._metrics = metrics or {"cpu_percent": 30.0, "ram_percent": 40.0}
        self.latencies: list[float] = []
        self.initialized = False

    async def initialize(self) -> None:
        self.initialized = True

    async def shutdown(self) -> None:
        pass

    async def read_metrics(self) -> dict[str, float]:
        return dict(self._metrics)

    def update_cycle_latency_sample(self, wall_duration_ms: float) -> None:
        self.latencies.append(float(wall_duration_ms))


class NeverAlertDetector:
    def evaluate(self, metrics: dict[str, float]) -> Any:
        from kaine.modules.interoception.detector import AlertResult
        return AlertResult()


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _make_hypnos_event(type_: str) -> Event:
    return Event(
        source="hypnos",
        type=type_,
        payload={},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_in_hypnos_false_at_start(bus: AsyncBus):
    pytest.importorskip("torch")
    interoception = Interoception(bus, reader=FakeMetricsReader(), detector=NeverAlertDetector())
    assert interoception._in_hypnos is False


@pytest.mark.asyncio
async def test_in_hypnos_true_after_sleep_started(bus: AsyncBus):
    pytest.importorskip("torch")
    interoception = Interoception(bus, reader=FakeMetricsReader(), detector=NeverAlertDetector())
    await interoception.initialize()
    try:
        await bus.publish(_make_hypnos_event("hypnos.sleep.started"))
        # Allow the sleep consumer task to drain the event.
        for _ in range(100):
            if interoception._in_hypnos:
                break
            await asyncio.sleep(0.01)
        assert interoception._in_hypnos is True
    finally:
        await interoception.shutdown()


@pytest.mark.asyncio
async def test_weights_frozen_during_hypnos(bus: AsyncBus):
    """Forward-model weights must not change while _in_hypnos is True."""
    pytest.importorskip("torch")
    interoception = Interoception(bus, reader=FakeMetricsReader(), detector=NeverAlertDetector())
    await interoception.initialize()
    try:
        # Do a warm-up tick to get a non-None last_prediction.
        await interoception.tick_once()

        # Enter the sleep module.
        await bus.publish(_make_hypnos_event("hypnos.sleep.started"))
        for _ in range(100):
            if interoception._in_hypnos:
                break
            await asyncio.sleep(0.01)
        assert interoception._in_hypnos is True

        # Snapshot weights before ticks during sleep.
        before = interoception._forward_model.state_dict()

        # Several ticks during sleep should not change weights.
        for _ in range(5):
            await interoception.tick_once()

        after = interoception._forward_model.state_dict()
        assert before["weight"] == after["weight"]
        assert before["bias"] == after["bias"]
    finally:
        await interoception.shutdown()


@pytest.mark.asyncio
async def test_in_hypnos_false_after_sleep_completed(bus: AsyncBus):
    pytest.importorskip("torch")
    interoception = Interoception(bus, reader=FakeMetricsReader(), detector=NeverAlertDetector())
    await interoception.initialize()
    try:
        await bus.publish(_make_hypnos_event("hypnos.sleep.started"))
        for _ in range(100):
            if interoception._in_hypnos:
                break
            await asyncio.sleep(0.01)
        assert interoception._in_hypnos is True

        await bus.publish(_make_hypnos_event("hypnos.sleep.completed"))
        for _ in range(100):
            if not interoception._in_hypnos:
                break
            await asyncio.sleep(0.01)
        assert interoception._in_hypnos is False
    finally:
        await interoception.shutdown()


@pytest.mark.asyncio
async def test_adaptation_resumes_after_sleep_completed(bus: AsyncBus):
    """After hypnos.sleep.completed, online adaptation must be re-enabled."""
    pytest.importorskip("torch")
    interoception = Interoception(bus, reader=FakeMetricsReader(), detector=NeverAlertDetector())
    await interoception.initialize()
    try:
        # Enter and exit the sleep module.
        await bus.publish(_make_hypnos_event("hypnos.sleep.started"))
        for _ in range(100):
            if interoception._in_hypnos:
                break
            await asyncio.sleep(0.01)

        await bus.publish(_make_hypnos_event("hypnos.sleep.completed"))
        for _ in range(100):
            if not interoception._in_hypnos:
                break
            await asyncio.sleep(0.01)

        assert interoception._in_hypnos is False

        # After a warm-up tick, weights should change (suspended=False).
        await interoception.tick_once()   # warm-up: sets last_prediction
        before = interoception._forward_model.state_dict()
        # Multiple adaptation ticks.
        for _ in range(5):
            await interoception.tick_once()
        after = interoception._forward_model.state_dict()

        # Weights must have changed (adaptation is active).
        any_changed = before["weight"] != after["weight"] or before["bias"] != after["bias"]
        assert any_changed, "weights did not change after resuming adaptation"
    finally:
        await interoception.shutdown()


@pytest.mark.asyncio
async def test_fatigue_reset_on_sleep_completed(bus: AsyncBus):
    """Fatigue accumulator is reset to zero when hypnos.sleep.completed fires."""
    pytest.importorskip("torch")
    interoception = Interoception(bus, reader=FakeMetricsReader(), detector=NeverAlertDetector())
    await interoception.initialize()
    try:
        # Seed some fatigue.
        interoception._fatigue._value = 55.0

        await bus.publish(_make_hypnos_event("hypnos.sleep.completed"))
        for _ in range(100):
            if not interoception._in_hypnos and interoception._fatigue.value == 0.0:
                break
            await asyncio.sleep(0.01)

        assert interoception._fatigue.value == 0.0
    finally:
        await interoception.shutdown()
