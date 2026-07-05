# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Phase 1: the shared subjective EntityClock + the cycle pacing through it.

These tests pin the hard invariants of the biological-timing-and-dilation
change, Phase 1:

  * subjective-time math: now() scales with time_scale; wall() never does;
  * time_scale = 0.5 makes the cycle sleep ~2x real per subjective tick;
  * time_scale = 0 is freeze semantics (no divide-by-zero; sleep is a no-op);
  * the deterministic logical clock is byte-identical at scale 1.0 to the
    pre-change formula (the top-priority behavior-identical invariant);
  * every rate change — including the Soma reduce_rate advisory — recomputes the
    cached tick period (the divergence-bug regression);
  * with shipped defaults (time_scale 1.0, unchanged rates) the engine behaves
    as before.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from kaine.bus.schema import Event
from kaine.cycle.engine import BASE_EPOCH, CognitiveCycle
from kaine.entity_clock import EntityClock
from tests._fakes import FakeClock, FakeRegistry, FakeSyneidesis


# ----------------------------------------------------------------------------
# A controllable real-clock/real-sleep pair (real seconds, deterministic).
# ----------------------------------------------------------------------------


class ManualClock:
    """A monotonic clock that only advances when `tick`/`sleep` move it.

    Distinct from tests._fakes.FakeClock so the EntityClock's *real* clock can be
    driven independently of the cycle engine's slip clock when needed.
    """

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


# ----------------------------------------------------------------------------
# 1. Subjective-time math
# ----------------------------------------------------------------------------


def test_now_scales_wall_does_not():
    clk = ManualClock(start=1000.0)
    ec = EntityClock(scale=2.0, monotonic=clk, real_sleep=clk.sleep)
    # At construction now() == origin (0.0) and wall() == real time.
    assert ec.now() == pytest.approx(0.0)
    assert ec.wall() == pytest.approx(1000.0)
    # Advance 3 real seconds.
    clk.advance(3.0)
    # Subjective time advanced by 3 * scale = 6.0; wall by exactly 3.0.
    assert ec.now() == pytest.approx(6.0)
    assert ec.wall() == pytest.approx(1003.0)


def test_scale_one_now_tracks_real_elapsed():
    clk = ManualClock(start=0.0)
    ec = EntityClock(scale=1.0, monotonic=clk, real_sleep=clk.sleep)
    clk.advance(5.0)
    assert ec.now() == pytest.approx(5.0)
    assert ec.scale == 1.0


def test_period_is_real_seconds_per_subjective_tick():
    clk = ManualClock()
    # scale 1.0: period(10 Hz) = 0.1 real s
    assert EntityClock(scale=1.0, monotonic=clk).period(10.0) == pytest.approx(0.1)
    # scale 0.5: period(10 Hz) = 1/(10*0.5) = 0.2 real s (slower, 2x)
    assert EntityClock(scale=0.5, monotonic=clk).period(10.0) == pytest.approx(0.2)
    # scale 2.0: period(10 Hz) = 1/(10*2) = 0.05 real s (faster, half)
    assert EntityClock(scale=2.0, monotonic=clk).period(10.0) == pytest.approx(0.05)


@pytest.mark.asyncio
async def test_sleep_scales_to_real_time():
    clk = ManualClock()
    ec = EntityClock(scale=0.5, monotonic=clk, real_sleep=clk.sleep)
    # Sleeping 1 subjective second at scale 0.5 takes 2 real seconds.
    await ec.sleep(1.0)
    assert clk.real_sleeps == [pytest.approx(2.0)]
    # scale 2.0 -> half the real wait.
    clk2 = ManualClock()
    ec2 = EntityClock(scale=2.0, monotonic=clk2, real_sleep=clk2.sleep)
    await ec2.sleep(1.0)
    assert clk2.real_sleeps == [pytest.approx(0.5)]


def test_scale_setter_reanchors_continuously():
    clk = ManualClock(start=0.0)
    ec = EntityClock(scale=1.0, monotonic=clk, real_sleep=clk.sleep)
    clk.advance(4.0)
    assert ec.now() == pytest.approx(4.0)
    # Change scale: subjective time must not jump, only its future rate changes.
    ec.scale = 3.0
    assert ec.now() == pytest.approx(4.0)
    clk.advance(2.0)
    assert ec.now() == pytest.approx(4.0 + 2.0 * 3.0)


def test_negative_scale_rejected():
    with pytest.raises(ValueError):
        EntityClock(scale=-1.0)
    ec = EntityClock(scale=1.0)
    with pytest.raises(ValueError):
        ec.scale = -0.5


# ----------------------------------------------------------------------------
# 2. scale = 0 freeze semantics (no divide-by-zero)
# ----------------------------------------------------------------------------


def test_scale_zero_now_is_frozen():
    clk = ManualClock(start=10.0)
    ec = EntityClock(scale=0.0, monotonic=clk, real_sleep=clk.sleep)
    clk.advance(100.0)
    # Subjective time does not advance while frozen; wall still does.
    assert ec.now() == pytest.approx(0.0)
    assert ec.wall() == pytest.approx(110.0)


@pytest.mark.asyncio
async def test_scale_zero_sleep_is_noop_not_divide_by_zero():
    clk = ManualClock()
    ec = EntityClock(scale=0.0, monotonic=clk, real_sleep=clk.sleep)
    # Must not raise ZeroDivisionError and must not actually sleep — the entity
    # is frozen via the pause path, not by waiting here.
    await ec.sleep(5.0)
    assert clk.real_sleeps == []


def test_scale_zero_period_is_undefined():
    ec = EntityClock(scale=0.0)
    with pytest.raises(ValueError):
        ec.period(10.0)


# ----------------------------------------------------------------------------
# Engine wiring helpers
# ----------------------------------------------------------------------------


def _build_engine(*, scale: float = 1.0, rate: float = 5.0, clock=None, sleep=None):
    """A minimal CognitiveCycle over fakes, paced through an EntityClock built
    from the SAME injected real-clock/real-sleep (so pacing is deterministic)."""
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    from kaine.bus.client import AsyncBus
    from kaine.bus.config import BusConfig

    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    cycle = CognitiveCycle(
        bus=bus,
        syneidesis=FakeSyneidesis(),
        registry=FakeRegistry([]),
        processing_rate_hz=rate,
        experiential_rate_hz=rate,
        clock=clock,
        sleep=sleep,
        time_scale=scale,
    )
    return cycle, bus


# ----------------------------------------------------------------------------
# 3. scale = 0.5 halves pacing (cycle sleeps ~2x real per subjective tick)
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scale_half_doubles_real_pacing():
    # A near-instant tick at 5 Hz: subjective period 0.2 s. At scale 1.0 the cycle
    # sleeps ~0.2 real s; at scale 0.5 it sleeps ~0.4 real s (2x real per tick).
    clk1 = FakeClock()
    cycle1, bus1 = _build_engine(scale=1.0, rate=5.0, clock=clk1, sleep=clk1.sleep)
    await cycle1.run_forever(max_ticks=2)
    real_sleep_at_1 = sum(clk1.sleeps)
    await bus1.close()

    clk2 = FakeClock()
    cycle2, bus2 = _build_engine(scale=0.5, rate=5.0, clock=clk2, sleep=clk2.sleep)
    await cycle2.run_forever(max_ticks=2)
    real_sleep_at_half = sum(clk2.sleeps)
    await bus2.close()

    assert real_sleep_at_1 == pytest.approx(0.2, abs=1e-6)
    assert real_sleep_at_half == pytest.approx(0.4, abs=1e-6)
    # The defining ratio: half scale ⇒ twice the real pacing.
    assert real_sleep_at_half == pytest.approx(2.0 * real_sleep_at_1, abs=1e-6)


@pytest.mark.asyncio
async def test_scale_two_halves_real_pacing():
    clk = FakeClock()
    cycle, bus = _build_engine(scale=2.0, rate=5.0, clock=clk, sleep=clk.sleep)
    await cycle.run_forever(max_ticks=2)
    # subjective period 0.2 s, real budget 0.1 s at scale 2.0.
    assert sum(clk.sleeps) == pytest.approx(0.1, abs=1e-6)
    await bus.close()


# ----------------------------------------------------------------------------
# 4. Deterministic logical clock byte-identical at scale 1.0 (and at any scale)
# ----------------------------------------------------------------------------


def _logical_engine(*, scale: float, rate: float = 3.333) -> CognitiveCycle:
    clk = FakeClock()
    return CognitiveCycle(
        bus=_NullBus(),
        syneidesis=FakeSyneidesis(),
        registry=FakeRegistry([]),
        processing_rate_hz=rate,
        experiential_rate_hz=rate,
        clock=clk,
        sleep=clk.sleep,
        deterministic=True,
        time_scale=scale,
    )


class _NullBus:
    async def read(self, *a, **k):
        return []

    async def publish(self, event):
        return "x"

    async def publish_workspace(self, snapshot, source="syneidesis"):
        return "x"

    async def close(self):
        return None


def test_logical_clock_identical_at_scale_one_to_pre_change_formula():
    # Pre-change formula: tick k -> BASE_EPOCH + k * (1/rate). The logical clock
    # stamps in SUBJECTIVE time (period = 1/rate), which is invariant under scale,
    # so it must equal this at scale 1.0 exactly (the behavior-identical invariant).
    rate = 3.333
    cycle = _logical_engine(scale=1.0, rate=rate)
    period = 1.0 / rate
    for k in range(8):
        cycle._tick_index = k
        assert cycle._logical_now() == BASE_EPOCH + timedelta(seconds=k * period)


def test_logical_clock_invariant_across_time_scales():
    # The subjective logical clock does NOT change with time_scale — only the REAL
    # pacing does. tick k stamps the same logical time at scale 0.5, 1.0, and 2.0.
    rate = 3.333
    period = 1.0 / rate
    for scale in (0.5, 1.0, 2.0):
        cycle = _logical_engine(scale=scale, rate=rate)
        for k in range(5):
            cycle._tick_index = k
            assert cycle._logical_now() == BASE_EPOCH + timedelta(seconds=k * period)


# ----------------------------------------------------------------------------
# 5. ALL rate changes recompute the cached period (divergence-bug regression)
# ----------------------------------------------------------------------------


def _period_for(cycle: CognitiveCycle) -> float:
    return cycle._target_tick_period_s


def test_set_processing_rate_recomputes_period():
    cycle = _logical_engine(scale=1.0, rate=5.0)
    cycle.set_processing_rate(10.0)
    assert _period_for(cycle) == pytest.approx(0.1)


@pytest.mark.asyncio
async def test_apply_rate_control_event_recomputes_period():
    cycle = _logical_engine(scale=1.0, rate=5.0)
    ok = await cycle.apply_rate_control_event({"processing_rate_hz": 4.0})
    assert ok
    assert _period_for(cycle) == pytest.approx(0.25)
    # And the logical clock now reflects the new period (would have stayed at the
    # stale 0.2 under the old direct-assignment bug).
    cycle._tick_index = 3
    assert cycle._logical_now() == BASE_EPOCH + timedelta(seconds=3 * 0.25)


@pytest.mark.asyncio
async def test_soma_reduce_rate_recomputes_period_regression():
    """The audit's divergence bug: reduce_rate used to mutate _processing_rate
    WITHOUT recomputing _target_tick_period, so the logical clock kept stamping at
    the stale period. Routing reduce_rate through the single setter fixes it."""
    cycle = _logical_engine(scale=1.0, rate=5.0)
    before_rate = cycle.processing_rate_hz
    # Feed a soma.regulation/reduce_rate advisory through the real consumer.
    bus = _ReduceRateBus()
    cycle._bus = bus  # type: ignore[assignment]
    await cycle.consume_soma_regulation()
    after_rate = cycle.processing_rate_hz
    assert after_rate < before_rate  # the throttle actually lowered the rate
    # The cached period must equal 1/new_rate — NOT the stale 1/before_rate.
    assert _period_for(cycle) == pytest.approx(1.0 / after_rate)
    assert _period_for(cycle) != pytest.approx(1.0 / before_rate)


class _ReduceRateBus(_NullBus):
    """A bus that yields exactly one soma.regulation/reduce_rate event."""

    def __init__(self) -> None:
        self._served = False

    async def read(self, stream, last_id="0", count=100, block_ms=0):
        if stream == "soma.out" and not self._served:
            self._served = True
            return [
                (
                    "1-0",
                    Event(
                        source="soma",
                        type="soma.regulation",
                        payload={"action": "reduce_rate", "reason": "test", "severity": 2},
                        salience=0.5,
                        timestamp=BASE_EPOCH,
                    ),
                )
            ]
        return []


# ----------------------------------------------------------------------------
# 6. Behavior-identical default
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_time_scale_is_one_and_paces_as_before():
    # With NO time_scale arg the engine defaults to 1.0 and paces exactly as the
    # pre-change engine: a near-instant tick at 5 Hz sleeps ~0.2 real s, and the
    # reported target_duration_ms is 1000/rate.
    clk = FakeClock()
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    from kaine.bus.client import AsyncBus
    from kaine.bus.config import BusConfig

    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    cycle = CognitiveCycle(
        bus=bus,
        syneidesis=FakeSyneidesis(),
        registry=FakeRegistry([]),
        processing_rate_hz=5.0,
        experiential_rate_hz=5.0,
        clock=clk,
        sleep=clk.sleep,
    )
    assert cycle.time_scale == 1.0
    result = await cycle.tick()
    assert result.target_duration_ms == pytest.approx(200.0, rel=1e-6)
    await bus.close()

    # Pace one tick from a fresh engine: ~0.2 real s slept (1000/5 Hz).
    clk2 = FakeClock()
    client2 = fakeredis.FakeRedis(decode_responses=True)
    bus2 = AsyncBus(BusConfig(password="x", audit_required=False), client=client2)
    cycle2 = CognitiveCycle(
        bus=bus2,
        syneidesis=FakeSyneidesis(),
        registry=FakeRegistry([]),
        processing_rate_hz=5.0,
        experiential_rate_hz=5.0,
        clock=clk2,
        sleep=clk2.sleep,
    )
    await cycle2.run_forever(max_ticks=2)
    assert sum(clk2.sleeps) == pytest.approx(0.2, abs=1e-6)
    await bus2.close()
