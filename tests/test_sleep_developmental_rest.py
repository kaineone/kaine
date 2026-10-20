# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the developmental rest triggered by affect.rest_request (paper §3.5).

The developmental rest starts when the stimulus is spent, holds for
developmental_rest_s (default 1260 s), and ends with an affective reset.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kaine.boot.factories.sleep import make_sleep
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import validate_event
from kaine.modules.sleep import (
    FakeTrainer,
    Sleep,
    VoiceAlignmentConfig,
)


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


async def _wait_for_started(bus: AsyncBus, trigger: str, timeout: float = 2.0) -> dict:
    """Poll sleep.out until a sleep.sleep.started event with ``trigger`` appears."""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        entries = await bus.read("sleep.out", last_id="0", count=1000)
        for _, event in entries:
            if event.type == "sleep.sleep.started" and event.payload.get("trigger") == trigger:
                return event.payload
        if asyncio.get_running_loop().time() >= deadline:
            raise asyncio.TimeoutError(f"no sleep.sleep.started with trigger {trigger!r}")
        await asyncio.sleep(0.02)


async def _publish_rest_request(bus: AsyncBus, reason: str) -> None:
    event = validate_event(
        source="affect",
        type="affect.rest_request",
        payload={"reason": reason, "drive": "boredom", "stall_s": 120.0},
        salience=0.6,
        timestamp=datetime.now(timezone.utc),
    )
    await bus.publish(event)


@pytest.mark.asyncio
async def test_stimulus_spent_rest_request_triggers_developmental_rest(bus: AsyncBus, tmp_path: Path):
    """affect.rest_request with reason stimulus_spent starts a developmental rest."""
    sleep = _make_sleep(bus, tmp_path, developmental_rest_s=3600.0)
    await sleep.initialize()

    await _publish_rest_request(bus, "stimulus_spent")
    payload = await _wait_for_started(bus, "developmental_rest", timeout=2.0)

    assert payload["trigger"] == "developmental_rest"
    await sleep.shutdown()


@pytest.mark.asyncio
async def test_non_stimulus_rest_request_does_not_trigger_rest(bus: AsyncBus, tmp_path: Path):
    """Only reason stimulus_spent triggers a developmental rest."""
    sleep = _make_sleep(bus, tmp_path, developmental_rest_s=3600.0)
    await sleep.initialize()

    # Another reason on affect.rest_request
    await _publish_rest_request(bus, "other_reason")

    # Another affect event type
    event = validate_event(
        source="affect",
        type="affect.regulation",
        payload={"action": "request_maintenance"},
        salience=0.6,
        timestamp=datetime.now(timezone.utc),
    )
    await bus.publish(event)

    with pytest.raises(asyncio.TimeoutError):
        await _wait_for_started(bus, "developmental_rest", timeout=0.3)

    await sleep.shutdown()


@pytest.mark.asyncio
async def test_developmental_rest_holds_for_configured_duration(bus: AsyncBus, tmp_path: Path):
    """The developmental rest holds for developmental_rest_s before the affective reset."""
    t0 = time.monotonic()
    fake_clock = FakeEntityClock(offset=t0)
    affect = FakeAffect()
    sleep = _make_sleep(
        bus,
        tmp_path,
        developmental_rest_s=0.6,
        entity_clock=fake_clock,
        affect=affect,
    )

    start = time.monotonic()
    summary = await sleep.enter_sleep(trigger="developmental_rest")
    elapsed = time.monotonic() - start

    assert elapsed >= 0.55, f"expected at least ~0.6 s hold, got {elapsed:.3f} s"
    assert affect.reset_at is not None
    assert affect.reset_at - start >= 0.55
    assert summary.get("trigger") == "developmental_rest"
    assert summary.get("rest_seconds") == pytest.approx(0.6)
    await sleep.shutdown()


@pytest.mark.asyncio
async def test_ordinary_sleep_is_not_held(bus: AsyncBus, tmp_path: Path):
    """A sleep without the developmental trigger returns quickly and has no rest keys."""
    sleep = _make_sleep(bus, tmp_path, developmental_rest_s=0.6)

    start = time.monotonic()
    summary = await sleep.enter_sleep()
    elapsed = time.monotonic() - start

    assert elapsed < 0.3
    assert "trigger" not in summary
    assert "rest_seconds" not in summary
    await sleep.shutdown()


@pytest.mark.asyncio
async def test_developmental_rest_cancel_runs_affective_reset_and_aborts(bus: AsyncBus, tmp_path: Path):
    """A cancel during the hold still runs the affective reset and publishes aborted completion."""
    affect = FakeAffect()
    sleep = _make_sleep(
        bus,
        tmp_path,
        developmental_rest_s=30.0,
        affect=affect,
    )

    task = asyncio.create_task(sleep.enter_sleep(trigger="developmental_rest"))
    await asyncio.sleep(0.3)
    task.cancel()
    (outcome,) = await asyncio.gather(task, return_exceptions=True)
    assert isinstance(outcome, asyncio.CancelledError)

    # The abort path publishes sleep.sleep.completed with aborted true.
    payload = None
    deadline = asyncio.get_running_loop().time() + 2.0
    while payload is None and asyncio.get_running_loop().time() < deadline:
        entries = await bus.read("sleep.out", last_id="0", count=1000)
        for _, event in entries:
            if event.type == "sleep.sleep.completed":
                payload = event.payload
        if payload is None:
            await asyncio.sleep(0.02)
    if payload is None:
        pytest.fail("sleep.sleep.completed was not published after cancel")

    assert payload.get("aborted") is True
    assert affect.reset_at is not None
    assert not sleep._sleep_lock.locked()
    await sleep.shutdown()


@pytest.mark.asyncio
async def test_second_rest_request_while_holding_is_guarded(bus: AsyncBus, tmp_path: Path):
    """A second affect.rest_request during a developmental rest cannot start another sleep."""
    sleep = _make_sleep(bus, tmp_path, developmental_rest_s=1.0)
    await sleep.initialize()

    await _publish_rest_request(bus, "stimulus_spent")
    first_payload = await _wait_for_started(bus, "developmental_rest", timeout=2.0)
    assert first_payload["trigger"] == "developmental_rest"

    # While the rest holds, publish a second request.
    await _publish_rest_request(bus, "stimulus_spent")
    await asyncio.sleep(0.3)

    started_events = []
    entries = await bus.read("sleep.out", last_id="0", count=1000)
    for _, event in entries:
        if event.type == "sleep.sleep.started" and event.payload.get("trigger") == "developmental_rest":
            started_events.append(event.payload)

    assert len(started_events) == 1
    await sleep.shutdown()


@pytest.mark.asyncio
async def test_developmental_rest_s_validation(bus: AsyncBus, tmp_path: Path):
    """Sleep rejects non-finite or non-positive developmental_rest_s."""
    for bad in (0, -1, float("nan"), float("inf"), True):
        with pytest.raises(ValueError):
            Sleep(bus, developmental_rest_s=bad)


@pytest.mark.asyncio
async def test_make_sleep_passes_and_rejects_developmental_rest_s(bus: AsyncBus, tmp_path: Path):
    """Factory forwards a valid developmental_rest_s and rejects bad values."""
    # Pass a valid configured value.
    sleep = make_sleep(bus, {"developmental_rest_s": 900.0})
    assert sleep._developmental_rest_s == 900.0
    await sleep.shutdown()

    # Reject a bad value.
    with pytest.raises(ValueError, match="developmental_rest_s"):
        make_sleep(bus, {"developmental_rest_s": -5.0})
