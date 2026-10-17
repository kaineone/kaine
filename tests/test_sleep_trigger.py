# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for sleep fatigue-triggered entry and safety-net interval (tasks 7.1).

Covers:
- interoception.fatigue crossed=true triggers a maintenance cycle (fatigue trigger)
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

    async def affective_reset(self) -> None:
        self.resets += 1


def _make_sleep(bus: AsyncBus, tmp_path: Path, **kwargs) -> Sleep:
    config = VoiceAlignmentConfig(
        intent_log_path=tmp_path / "intent.jsonl",
        adapter_output_dir=tmp_path / "adapters",
        enabled=False,
    )
    return Sleep(
        bus,
        episodic_memory=FakeEpisodicMemory(),
        affect=FakeAffect(),
        trainer=FakeTrainer(),
        voice_alignment_config=config,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Test 1: interoception.fatigue crossed=true triggers maintenance
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_interoception_fatigue_triggers_maintenance(bus: AsyncBus, tmp_path: Path):
    """When interoception.fatigue with crossed=true is published, the sleep module triggers sleep."""
    sleep = _make_sleep(bus, tmp_path, fatigue_triggered=True)
    # Initialise (seeds the interoception module's cursor and starts consumer loop)
    await sleep.initialize()

    sleep_fired = asyncio.Event()
    original_run = sleep._run_pipeline

    async def _mock_run():
        sleep_fired.set()
        return await original_run()

    sleep._run_pipeline = _mock_run

    # Publish interoception.fatigue with crossed=true
    from datetime import datetime, timezone

    from kaine.bus.schema import validate_event

    event = validate_event(
        source="interoception",
        type="interoception.fatigue",
        payload={"value": 105.0, "threshold": 100.0, "crossed": True},
        salience=0.7,
        timestamp=datetime.now(timezone.utc),
    )
    await bus.publish(event)

    # Give the consumer loop time to process
    try:
        await asyncio.wait_for(sleep_fired.wait(), timeout=2.0)
    except asyncio.TimeoutError:
        pytest.fail("interoception.fatigue trigger did not fire maintenance cycle within 2s")

    await sleep.shutdown()


@pytest.mark.asyncio
async def test_interoception_regulation_request_maintenance_triggers(bus: AsyncBus, tmp_path: Path):
    """interoception.regulation with action=request_maintenance triggers a sleep cycle."""
    sleep = _make_sleep(bus, tmp_path, fatigue_triggered=True)
    await sleep.initialize()

    sleep_fired = asyncio.Event()
    original_run = sleep._run_pipeline

    async def _mock_run():
        sleep_fired.set()
        return await original_run()

    sleep._run_pipeline = _mock_run

    from datetime import datetime, timezone

    from kaine.bus.schema import validate_event

    event = validate_event(
        source="interoception",
        type="interoception.regulation",
        payload={"action": "request_maintenance", "reason": "stress", "severity": 3},
        salience=0.7,
        timestamp=datetime.now(timezone.utc),
    )
    await bus.publish(event)

    try:
        await asyncio.wait_for(sleep_fired.wait(), timeout=2.0)
    except asyncio.TimeoutError:
        pytest.fail(
            "interoception.regulation request_maintenance did not fire maintenance within 2s"
        )

    await sleep.shutdown()


@pytest.mark.asyncio
async def test_interoception_regulation_other_action_does_not_trigger(bus: AsyncBus, tmp_path: Path):
    """interoception.regulation with a non-maintenance action must NOT trigger sleep."""
    sleep = _make_sleep(bus, tmp_path, fatigue_triggered=True)
    await sleep.initialize()

    sleep_fired = asyncio.Event()
    original_run = sleep._run_pipeline

    async def _mock_run():
        sleep_fired.set()
        return await original_run()

    sleep._run_pipeline = _mock_run

    from datetime import datetime, timezone

    from kaine.bus.schema import validate_event

    event = validate_event(
        source="interoception",
        type="interoception.regulation",
        payload={"action": "reduce_rate", "reason": "stress", "severity": 1},
        salience=0.3,
        timestamp=datetime.now(timezone.utc),
    )
    await bus.publish(event)

    await asyncio.sleep(0.15)
    assert not sleep_fired.is_set(), "reduce_rate must not trigger maintenance"
    await sleep.shutdown()


@pytest.mark.asyncio
async def test_interoception_fatigue_not_crossed_does_not_trigger(bus: AsyncBus, tmp_path: Path):
    """interoception.fatigue with crossed=false should NOT trigger maintenance."""
    sleep = _make_sleep(bus, tmp_path, fatigue_triggered=True)
    await sleep.initialize()

    sleep_fired = asyncio.Event()
    original_run = sleep._run_pipeline

    async def _mock_run():
        sleep_fired.set()
        return await original_run()

    sleep._run_pipeline = _mock_run

    from datetime import datetime, timezone

    from kaine.bus.schema import validate_event

    event = validate_event(
        source="interoception",
        type="interoception.fatigue",
        payload={"value": 50.0, "threshold": 100.0, "crossed": False},
        salience=0.1,
        timestamp=datetime.now(timezone.utc),
    )
    await bus.publish(event)

    # Sleep should NOT have fired within a short window.
    await asyncio.sleep(0.15)
    assert not sleep_fired.is_set(), "crossed=false should not trigger maintenance"
    await sleep.shutdown()


@pytest.mark.asyncio
async def test_affect_regulation_request_maintenance_triggers(bus: AsyncBus, tmp_path: Path):
    """affect.regulation with tier=3 and action=request_maintenance triggers a sleep cycle."""
    sleep = _make_sleep(bus, tmp_path, fatigue_triggered=True)
    await sleep.initialize()

    sleep_fired = asyncio.Event()
    original_run = sleep._run_pipeline

    async def _mock_run():
        sleep_fired.set()
        return await original_run()

    sleep._run_pipeline = _mock_run

    from datetime import datetime, timezone

    from kaine.bus.schema import validate_event

    event = validate_event(
        source="affect",
        type="affect.regulation",
        payload={"tier": 3, "action": "request_maintenance", "size": 0.8},
        salience=0.7,
        timestamp=datetime.now(timezone.utc),
    )
    await bus.publish(event)

    try:
        await asyncio.wait_for(sleep_fired.wait(), timeout=2.0)
    except asyncio.TimeoutError:
        pytest.fail(
            "affect.regulation request_maintenance did not fire maintenance within 2s"
        )

    await sleep.shutdown()


@pytest.mark.asyncio
async def test_affect_regulation_other_tier_does_not_trigger(bus: AsyncBus, tmp_path: Path):
    """affect.regulation with tier 1 and tier 2 actions must NOT trigger sleep."""
    sleep = _make_sleep(bus, tmp_path, fatigue_triggered=True)
    await sleep.initialize()

    sleep_fired = asyncio.Event()
    original_run = sleep._run_pipeline

    async def _mock_run():
        sleep_fired.set()
        return await original_run()

    sleep._run_pipeline = _mock_run

    from datetime import datetime, timezone

    from kaine.bus.schema import validate_event

    tier1_event = validate_event(
        source="affect",
        type="affect.regulation",
        payload={"tier": 1, "action": "attentional_deployment"},
        salience=0.3,
        timestamp=datetime.now(timezone.utc),
    )
    tier2_event = validate_event(
        source="affect",
        type="affect.regulation",
        payload={"tier": 2, "action": "reappraisal"},
        salience=0.3,
        timestamp=datetime.now(timezone.utc),
    )
    await bus.publish(tier1_event)
    await bus.publish(tier2_event)

    await asyncio.sleep(0.15)
    assert not sleep_fired.is_set(), "tier 1 / tier 2 affect regulation must not trigger maintenance"
    await sleep.shutdown()


@pytest.mark.asyncio
async def test_affect_request_ignored_when_fatigue_trigger_off(bus: AsyncBus, tmp_path: Path):
    """With fatigue_triggered=False, a tier-3 affect request does not start a sleep."""
    sleep = _make_sleep(bus, tmp_path, fatigue_triggered=False)
    await sleep.initialize()

    sleep_fired = asyncio.Event()
    original_run = sleep._run_pipeline

    async def _mock_run():
        sleep_fired.set()
        return await original_run()

    sleep._run_pipeline = _mock_run

    from datetime import datetime, timezone

    from kaine.bus.schema import validate_event

    event = validate_event(
        source="affect",
        type="affect.regulation",
        payload={"tier": 3, "action": "request_maintenance", "size": 0.8},
        salience=0.7,
        timestamp=datetime.now(timezone.utc),
    )
    await bus.publish(event)

    await asyncio.sleep(0.15)
    assert not sleep_fired.is_set(), "tier-3 affect request must not trigger maintenance when fatigue_triggered is False"
    await sleep.shutdown()


# ---------------------------------------------------------------------------
# Test 2: interval_seconds safety-net fires even without fatigue
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_safety_net_interval_fires_without_fatigue(bus: AsyncBus, tmp_path: Path):
    """interval_seconds fires as a safety net even if interoception.fatigue never crosses.

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
    sleep = _make_sleep(
        bus, tmp_path, scheduler=scheduler, fatigue_triggered=True
    )

    # Not due yet
    assert not sleep.is_due()

    # Advance time past the interval
    now_val[0] = 10.0
    assert sleep.is_due()

    # Safety-net sleep fires
    summary = await sleep.enter_sleep()
    assert "phases" in summary

    # After completion, not due again
    assert not sleep.is_due()


# ---------------------------------------------------------------------------
# Test 3: non-interruptibility (SleepBusyError while sleeping)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_non_interruptibility_during_fatigue_sleep(bus: AsyncBus, tmp_path: Path):
    """While a fatigue-triggered sleep is in progress, a second call raises."""
    class SlowEpisodicMemory(FakeEpisodicMemory):
        async def consolidate_now(self) -> int:
            await asyncio.sleep(0.1)
            return 0

    config = VoiceAlignmentConfig(
        intent_log_path=tmp_path / "intent.jsonl",
        adapter_output_dir=tmp_path / "adapters",
        enabled=False,
    )
    sleep = Sleep(
        bus,
        episodic_memory=SlowEpisodicMemory(),
        affect=FakeAffect(),
        trainer=FakeTrainer(),
        voice_alignment_config=config,
    )
    first = asyncio.create_task(sleep.enter_sleep())
    await asyncio.sleep(0.02)  # let first start
    with pytest.raises(SleepBusyError):
        await sleep.enter_sleep()
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
