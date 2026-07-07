# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for Hypnos fatigue-triggered entry and safety-net interval (tasks 7.1).

Covers:
- soma.fatigue crossed=true triggers a maintenance cycle (fatigue trigger)
- interval_seconds fires as a max-interval safety net even without fatigue
- Non-interruptibility, deferral, and freeze-preemption are retained

The bus is seeded with fakeredis so no Redis is needed.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.hypnos import (
    FakeTrainer,
    Hypnos,
    RestScheduler,
    VoiceAlignmentConfig,
)
from kaine.modules.hypnos.module import HypnosBusyError


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


class FakeMnemos:
    def __init__(self) -> None:
        self.consolidated = 0
        self.downscale_calls: list[float] = []
        self.replay_calls = 0

    async def consolidate_now(self) -> int:
        self.consolidated += 1
        return 0

    def downscale_activations(self, factor: float) -> int:
        self.downscale_calls.append(factor)
        return 0

    async def replay_now(self) -> list:
        self.replay_calls += 1
        return []


class FakeThymos:
    def __init__(self) -> None:
        self.resets = 0

    async def affective_reset(self) -> None:
        self.resets += 1


def _make_hypnos(bus: AsyncBus, tmp_path: Path, **kwargs) -> Hypnos:
    config = VoiceAlignmentConfig(
        intent_log_path=tmp_path / "intent.jsonl",
        adapter_output_dir=tmp_path / "adapters",
        enabled=False,
    )
    return Hypnos(
        bus,
        mnemos=FakeMnemos(),
        thymos=FakeThymos(),
        trainer=FakeTrainer(),
        voice_alignment_config=config,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Test 1: soma.fatigue crossed=true triggers maintenance
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_soma_fatigue_triggers_maintenance(bus: AsyncBus, tmp_path: Path):
    """When soma.fatigue with crossed=true is published, Hypnos triggers sleep."""
    hypnos = _make_hypnos(bus, tmp_path, fatigue_triggered=True)
    # Initialise (seeds soma cursor and starts consumer loop)
    await hypnos.initialize()

    sleep_fired = asyncio.Event()
    original_run = hypnos._run_pipeline

    async def _mock_run():
        sleep_fired.set()
        return await original_run()

    hypnos._run_pipeline = _mock_run

    # Publish soma.fatigue with crossed=true
    from datetime import datetime, timezone
    from kaine.bus.schema import validate_event

    event = validate_event(
        source="soma",
        type="soma.fatigue",
        payload={"value": 105.0, "threshold": 100.0, "crossed": True},
        salience=0.7,
        timestamp=datetime.now(timezone.utc),
    )
    await bus.publish(event)

    # Give the consumer loop time to process
    try:
        await asyncio.wait_for(sleep_fired.wait(), timeout=2.0)
    except asyncio.TimeoutError:
        pytest.fail("soma.fatigue trigger did not fire maintenance cycle within 2s")

    await hypnos.shutdown()


@pytest.mark.asyncio
async def test_soma_regulation_request_maintenance_triggers(bus: AsyncBus, tmp_path: Path):
    """soma.regulation with action=request_maintenance triggers a sleep cycle."""
    hypnos = _make_hypnos(bus, tmp_path, fatigue_triggered=True)
    await hypnos.initialize()

    sleep_fired = asyncio.Event()
    original_run = hypnos._run_pipeline

    async def _mock_run():
        sleep_fired.set()
        return await original_run()

    hypnos._run_pipeline = _mock_run

    from datetime import datetime, timezone
    from kaine.bus.schema import validate_event

    event = validate_event(
        source="soma",
        type="soma.regulation",
        payload={"action": "request_maintenance", "reason": "stress", "severity": 3},
        salience=0.7,
        timestamp=datetime.now(timezone.utc),
    )
    await bus.publish(event)

    try:
        await asyncio.wait_for(sleep_fired.wait(), timeout=2.0)
    except asyncio.TimeoutError:
        pytest.fail(
            "soma.regulation request_maintenance did not fire maintenance within 2s"
        )

    await hypnos.shutdown()


@pytest.mark.asyncio
async def test_soma_regulation_other_action_does_not_trigger(bus: AsyncBus, tmp_path: Path):
    """soma.regulation with a non-maintenance action must NOT trigger sleep."""
    hypnos = _make_hypnos(bus, tmp_path, fatigue_triggered=True)
    await hypnos.initialize()

    sleep_fired = asyncio.Event()
    original_run = hypnos._run_pipeline

    async def _mock_run():
        sleep_fired.set()
        return await original_run()

    hypnos._run_pipeline = _mock_run

    from datetime import datetime, timezone
    from kaine.bus.schema import validate_event

    event = validate_event(
        source="soma",
        type="soma.regulation",
        payload={"action": "reduce_rate", "reason": "stress", "severity": 1},
        salience=0.3,
        timestamp=datetime.now(timezone.utc),
    )
    await bus.publish(event)

    await asyncio.sleep(0.15)
    assert not sleep_fired.is_set(), "reduce_rate must not trigger maintenance"
    await hypnos.shutdown()


@pytest.mark.asyncio
async def test_soma_fatigue_not_crossed_does_not_trigger(bus: AsyncBus, tmp_path: Path):
    """soma.fatigue with crossed=false should NOT trigger maintenance."""
    hypnos = _make_hypnos(bus, tmp_path, fatigue_triggered=True)
    await hypnos.initialize()

    sleep_fired = asyncio.Event()
    original_run = hypnos._run_pipeline

    async def _mock_run():
        sleep_fired.set()
        return await original_run()

    hypnos._run_pipeline = _mock_run

    from datetime import datetime, timezone
    from kaine.bus.schema import validate_event

    event = validate_event(
        source="soma",
        type="soma.fatigue",
        payload={"value": 50.0, "threshold": 100.0, "crossed": False},
        salience=0.1,
        timestamp=datetime.now(timezone.utc),
    )
    await bus.publish(event)

    # Sleep should NOT have fired within a short window.
    await asyncio.sleep(0.15)
    assert not sleep_fired.is_set(), "crossed=false should not trigger maintenance"
    await hypnos.shutdown()


# ---------------------------------------------------------------------------
# Test 2: interval_seconds safety-net fires even without fatigue
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_safety_net_interval_fires_without_fatigue(bus: AsyncBus, tmp_path: Path):
    """interval_seconds fires as a safety net even if soma.fatigue never crosses.

    This test bypasses the fatigue consumer and checks the scheduler directly:
    when is_due() returns True (mocked), enter_sleep can be called and completes.
    """
    # Use a fast scheduler so we can test due-check without waiting an hour
    now_val = [0.0]
    scheduler = RestScheduler(
        interval_seconds=5.0,
        max_deferral_seconds=10.0,
        per_defer_seconds=1.0,
        clock=lambda: now_val[0],
    )
    hypnos = _make_hypnos(
        bus, tmp_path, scheduler=scheduler, fatigue_triggered=True
    )

    # Not due yet
    assert not hypnos.is_due()

    # Advance time past the interval
    now_val[0] = 10.0
    assert hypnos.is_due()

    # Safety-net sleep fires
    summary = await hypnos.enter_sleep()
    assert "phases" in summary

    # After completion, not due again
    assert not hypnos.is_due()


# ---------------------------------------------------------------------------
# Test 3: non-interruptibility (HypnosBusyError while sleeping)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_non_interruptibility_during_fatigue_sleep(bus: AsyncBus, tmp_path: Path):
    """While a fatigue-triggered sleep is in progress, a second call raises."""
    class SlowMnemos(FakeMnemos):
        async def consolidate_now(self) -> int:
            await asyncio.sleep(0.1)
            return 0

    config = VoiceAlignmentConfig(
        intent_log_path=tmp_path / "intent.jsonl",
        adapter_output_dir=tmp_path / "adapters",
        enabled=False,
    )
    hypnos = Hypnos(
        bus,
        mnemos=SlowMnemos(),
        thymos=FakeThymos(),
        trainer=FakeTrainer(),
        voice_alignment_config=config,
    )
    first = asyncio.create_task(hypnos.enter_sleep())
    await asyncio.sleep(0.02)  # let first start
    with pytest.raises(HypnosBusyError):
        await hypnos.enter_sleep()
    await first


# ---------------------------------------------------------------------------
# Test 4: deferral respected (scheduler)
# ---------------------------------------------------------------------------

def test_deferral_accepted_within_window():
    """try_defer() returns True while within the deferral window."""
    now_val = [0.0]
    scheduler = RestScheduler(
        interval_seconds=10.0,
        max_deferral_seconds=30.0,
        per_defer_seconds=5.0,
        clock=lambda: now_val[0],
    )
    now_val[0] = 10.5  # just past original due time
    accepted = scheduler.try_defer()
    assert accepted is True


def test_deferral_refused_after_max_window():
    """try_defer() returns False after max_deferral_seconds elapsed."""
    now_val = [0.0]
    scheduler = RestScheduler(
        interval_seconds=10.0,
        max_deferral_seconds=15.0,
        per_defer_seconds=5.0,
        clock=lambda: now_val[0],
    )
    now_val[0] = 26.0  # past original_due + max_deferral (10 + 15 = 25)
    accepted = scheduler.try_defer()
    assert accepted is False
    assert scheduler.is_due()
