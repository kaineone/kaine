# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for housekeeping pressure scaling of awake fatigue (paper A.5)."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import pytest

from kaine.boot.factories.sleep import make_sleep
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.housekeeping_pressure import HousekeepingPressure, shared_pressure
from kaine.modules.interoception.fatigue import FatigueAccumulator
from kaine.modules.sleep import FakeTrainer, Sleep, VoiceAlignmentConfig

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
    def __init__(self, report: dict) -> None:
        self._report = report
        self.ran = 0

    async def run(self, *, episodic_store_bytes=None):
        self.ran += 1
        return dict(self._report)


class FailingHousekeeper:
    async def run(self, *, episodic_store_bytes=None):
        raise RuntimeError("housekeeping broke")


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


def _accumulator(**kwargs) -> FatigueAccumulator:
    kwargs.setdefault("decay_per_s", 0.0)
    kwargs.setdefault("maintenance_threshold", 100.0)
    return FatigueAccumulator(**kwargs)


def _value_after_one_step(pressure, *, asleep: bool = False) -> float:
    """Value after one 10 s step at e=0.5 with zero decay."""
    acc = _accumulator(pressure=pressure)
    if asleep:
        acc.faster_decay = True
    acc.update(0.0, now=0.0)
    acc.update(0.5, now=10.0)
    return acc.value


async def test_pressure_none_is_bit_identical_to_plain_accumulator():
    errors = [0.0, 0.4, 1.1, 0.0, 0.7, 0.2, 1.5, 0.3]
    plain = FatigueAccumulator(decay_per_s=0.05, maintenance_threshold=3.0)
    wired = FatigueAccumulator(
        decay_per_s=0.05, maintenance_threshold=3.0, pressure=None
    )
    t = 0.0
    for e in errors:
        t += 1.0
        plain_crossed = plain.update(e, now=t)
        wired_crossed = wired.update(e, now=t)
        assert wired_crossed == plain_crossed
        assert wired.value == plain.value
        probe = t + 1.0
        assert wired.would_cross(0.9, now=probe) == plain.would_cross(0.9, now=probe)
        # would_cross must not mutate either accumulator.
        assert wired.value == plain.value


async def test_pressure_one_doubles_awake_build_up():
    # One 10 s step at e=0.5, decay 0: 0.5 * (1 + 1) * 10 = 10.0 instead of 5.0.
    assert _value_after_one_step(lambda: 1.0) == 10.0
    assert _value_after_one_step(None) == 5.0


async def test_pressure_is_ignored_while_asleep():
    # faster_decay is set exactly while the entity sleeps; P^hk then reads 0.
    assert _value_after_one_step(lambda: 1.0, asleep=True) == 5.0


async def test_pressure_has_no_ceiling():
    # P^hk = 4 builds five times as fast: 0.5 * (1 + 4) * 10 = 25.0.
    assert _value_after_one_step(lambda: 4.0) == 25.0


async def test_unusable_pressure_counts_as_zero():
    def raising() -> float:
        raise RuntimeError("pressure read failed")

    assert _value_after_one_step(raising) == 5.0
    assert _value_after_one_step(lambda: float("nan")) == 5.0
    assert _value_after_one_step(lambda: float("inf")) == 5.0
    assert _value_after_one_step(lambda: -1.0) == 5.0
    assert _value_after_one_step(lambda: None) == 5.0


async def test_would_cross_agrees_with_update():
    acc = _accumulator(maintenance_threshold=9.0, pressure=lambda: 1.0)
    acc.update(0.0, now=0.0)
    # The step would build 0.5 * (1 + 1) * 10 = 10.0 >= 9.0: a new crossing.
    assert acc.would_cross(0.5, now=10.0) is True
    assert acc.update(0.5, now=10.0) is True
    # Already above the threshold: neither path reports a new crossing.
    assert acc.would_cross(0.5, now=20.0) is False
    assert acc.update(0.5, now=20.0) is False

    below = _accumulator(maintenance_threshold=11.0, pressure=lambda: 1.0)
    below.update(0.0, now=0.0)
    assert below.would_cross(0.5, now=10.0) is False
    assert below.update(0.5, now=10.0) is False


async def test_interoception_passes_pressure_to_fatigue_accumulator(bus):
    from kaine.modules.interoception.module import Interoception

    def pressure_fn() -> float:
        return 1.0

    module = Interoception(
        bus, forward_model=object(), housekeeping_pressure=pressure_fn
    )
    assert module._fatigue._pressure is pressure_fn


_HOUSEKEEPING_REPORT = {
    "terms": {"disk": 0.5, "memory": 0.0, "episodic": 0.0},
    "pressure": 0.5,
    "stopped": "within_budget",
    "moved_files": 0,
}


async def test_sleep_updates_pressure_from_housekeeping_report(bus, tmp_path):
    pressure = HousekeepingPressure()
    sleep = _make_sleep(
        bus,
        tmp_path,
        housekeeper=FakeHousekeeper(_HOUSEKEEPING_REPORT),
        housekeeping_pressure=pressure,
    )
    await sleep.enter_sleep()
    assert pressure.value() == 0.5


async def test_failing_housekeeper_leaves_previous_pressure(bus, tmp_path):
    pressure = HousekeepingPressure()
    pressure.set_from_sleep(
        {
            "terms": {"disk": 0.25, "memory": 0.0, "episodic": 0.0},
            "pressure": 0.25,
            "stopped": "within_budget",
            "moved_files": 0,
        }
    )
    assert pressure.value() == 0.25
    sleep = _make_sleep(
        bus,
        tmp_path,
        housekeeper=FailingHousekeeper(),
        housekeeping_pressure=pressure,
    )
    await sleep.enter_sleep()
    assert pressure.value() == 0.25


async def test_make_sleep_wires_shared_pressure(bus):
    sleep = make_sleep(bus, {})
    assert sleep._housekeeping_pressure is shared_pressure()
