# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import pytest

from kaine.entity_clock import EntityClock


class ManualClock:
    def __init__(self, start: float = 100.0) -> None:
        self._t = float(start)
        self.real_sleeps: list[float] = []

    def __call__(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds

    async def sleep(self, seconds: float) -> None:
        self.real_sleeps.append(seconds)
        self._t += seconds


def test_lockstep_rejects_nonunit_scale():
    mc = ManualClock()
    with pytest.raises(ValueError):
        EntityClock(scale=2.0, lockstep=True, monotonic=mc, real_sleep=mc.sleep)


def test_lockstep_constructor_stores_params():
    mc = ManualClock()
    c = EntityClock(lockstep=True, tick_period=0.1, monotonic=mc, real_sleep=mc.sleep)
    assert c.lockstep is True


def test_lockstep_now_advances_by_tick_period():
    mc = ManualClock()
    c = EntityClock(lockstep=True, tick_period=0.1, monotonic=mc, real_sleep=mc.sleep)
    assert c.now() == pytest.approx(0.0)
    c.advance_tick()
    assert c.now() == pytest.approx(0.1)
    c.advance_tick()
    c.advance_tick()
    c.advance_tick()
    assert c.now() == pytest.approx(0.4)
    mc.advance(1000.0)
    assert c.now() == pytest.approx(0.4)


def test_lockstep_now_deterministic_across_clocks():
    mc1 = ManualClock(start=0.0)
    mc2 = ManualClock(start=999.0)
    c1 = EntityClock(lockstep=True, tick_period=0.05, monotonic=mc1, real_sleep=mc1.sleep)
    c2 = EntityClock(lockstep=True, tick_period=0.05, monotonic=mc2, real_sleep=mc2.sleep)
    for _ in range(7):
        c1.advance_tick()
        c2.advance_tick()
    assert c1.now() == pytest.approx(c2.now())


@pytest.mark.asyncio
async def test_lockstep_sleep_is_noop():
    mc = ManualClock()
    c = EntityClock(lockstep=True, tick_period=0.1, monotonic=mc, real_sleep=mc.sleep)
    await c.sleep(5.0)
    assert mc.real_sleeps == []


def test_lockstep_advance_tick_raises_when_not_lockstep():
    mc = ManualClock()
    c = EntityClock(monotonic=mc, real_sleep=mc.sleep)
    with pytest.raises(RuntimeError):
        c.advance_tick()


def test_lockstep_scale_setter_raises():
    mc = ManualClock()
    c = EntityClock(lockstep=True, tick_period=0.1, monotonic=mc, real_sleep=mc.sleep)
    with pytest.raises(ValueError):
        c.scale = 0.5


def test_lockstep_period_returns_tick_period():
    mc = ManualClock()
    c = EntityClock(lockstep=True, tick_period=0.1, monotonic=mc, real_sleep=mc.sleep)
    assert c.period(10.0) == pytest.approx(0.1)
    assert c.period(5.0) == pytest.approx(0.1)


def test_lockstep_wall_still_works():
    mc = ManualClock(start=50.0)
    c = EntityClock(lockstep=True, tick_period=0.1, monotonic=mc, real_sleep=mc.sleep)
    assert c.wall() == pytest.approx(50.0)
    mc.advance(10.0)
    assert c.wall() == pytest.approx(60.0)


@pytest.mark.asyncio
async def test_non_lockstep_unchanged():
    mc = ManualClock(start=0.0)
    c = EntityClock(scale=2.0, monotonic=mc, real_sleep=mc.sleep)
    assert c.lockstep is False
    mc.advance(3.0)
    assert c.now() == pytest.approx(6.0)
    await c.sleep(1.0)
    assert mc.real_sleeps == [pytest.approx(0.5)]
