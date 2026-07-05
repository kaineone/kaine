# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Phase 2: cognitive module timers dilate with the shared EntityClock, while
infrastructure timers do NOT.

The load-bearing property of biological-timing-and-dilation Phase 2: one shared
``EntityClock`` is injected at boot into every cognitive module, so a single
``time_scale`` dilates their integrals/cadences coherently — and infrastructure
timers (watchdog polls, request timeouts, persistence cadences) stay on real
wall time regardless. These tests prove BOTH halves with the same scale knob:

  * a COGNITIVE timer scales — Soma's fatigue dt-integral accrues 2x at
    scale 2.0 and 0.5x at scale 0.5 for the SAME real elapsed time; the Topos
    capture cadence's real sleep halves at scale 2.0 / doubles at scale 0.5;
  * an INFRASTRUCTURE timer does NOT scale — a Spot liveness poll and a network
    request timeout are unchanged across scales;
  * ``build_registry`` injects ONE shared clock instance into every cognitive
    module AND exposes it on the registry so the cycle uses the same instance;
  * at the shipped default ``time_scale = 1.0`` every cognitive module behaves
    exactly as a real-time clock (covered by the unchanged module suites; the
    1.0 == real-time identity is re-asserted here for the fatigue integral).
"""
from __future__ import annotations

import pytest

from kaine.entity_clock import EntityClock


class ManualClock:
    """A monotonic source that only advances when ``advance`` moves it."""

    def __init__(self, start: float = 1000.0) -> None:
        self._t = float(start)

    def __call__(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


# ---------------------------------------------------------------------------
# COGNITIVE: Soma fatigue dt-integral scales with time_scale.
# ---------------------------------------------------------------------------


def _fatigue_after_two_ticks(scale: float, real_dt: float) -> float:
    """Drive a Soma fatigue accumulator through the injected subjective clock.

    First tick seeds ``_last_time``; the real clock then advances by
    ``real_dt`` and the second tick integrates ``e * dt`` where
    ``dt = clock.now() delta = real_dt * scale``. With ``decay_per_s = 0`` the
    accumulated fatigue is exactly ``e * real_dt * scale`` — linear in scale.
    """
    from kaine.modules.soma.fatigue import FatigueAccumulator

    clk = ManualClock()
    clock = EntityClock(scale=scale, monotonic=clk)
    acc = FatigueAccumulator(decay_per_s=0.0, maintenance_threshold=1e9)
    error = 4.0
    acc.update(error, now=clock.now())  # seed _last_time
    clk.advance(real_dt)
    acc.update(error, now=clock.now())
    return acc.value


def test_fatigue_integral_scales_with_time_scale():
    real_dt = 10.0
    error = 4.0
    base = _fatigue_after_two_ticks(scale=1.0, real_dt=real_dt)
    # At scale 1.0 the integral is the real-time value (behavior-identical).
    assert base == pytest.approx(error * real_dt)
    # Dilated-fast: twice the subjective dt → twice the fatigue.
    assert _fatigue_after_two_ticks(scale=2.0, real_dt=real_dt) == pytest.approx(
        2.0 * base
    )
    # Slowed: half the subjective dt → half the fatigue.
    assert _fatigue_after_two_ticks(scale=0.5, real_dt=real_dt) == pytest.approx(
        0.5 * base
    )


@pytest.mark.asyncio
async def test_soma_fatigue_through_module_scales(monkeypatch):
    """End-to-end through the Soma module: the SAME real elapsed time accrues
    more fatigue at a higher time_scale because the dt-integral reads the
    injected subjective clock."""
    pytest.importorskip("fakeredis.aioredis")
    from fakeredis.aioredis import FakeRedis

    from kaine.bus.client import AsyncBus
    from kaine.bus.config import BusConfig
    from kaine.modules.soma.module import Soma

    class _Reader:
        async def initialize(self) -> None: ...
        async def shutdown(self) -> None: ...
        async def read_metrics(self) -> dict[str, float]:
            # Constant metrics → deterministic, identical prediction-error
            # sequence across both Somas; only dt differs by scale.
            return {"cpu_percent": 50.0, "ram_percent": 50.0}
        def update_cycle_latency_sample(self, wall_duration_ms: float) -> None: ...

    async def _run(scale: float, clk: ManualClock) -> float:
        # Seed torch identically before each run so the two Somas' forward
        # models init to the SAME weights → identical prediction-error
        # sequences. Only the fatigue dt-integral then differs, and it differs
        # purely by time_scale — exactly the property under test.
        import torch

        torch.manual_seed(1234)
        bus = AsyncBus(
            BusConfig(password="x", audit_required=False),
            client=FakeRedis(decode_responses=True),
        )
        clock = EntityClock(scale=scale, monotonic=clk)
        soma = Soma(
            bus,
            reader=_Reader(),
            fatigue_decay_per_s=0.0,
            fatigue_maintenance_threshold=1e9,
            entity_clock=clock,
        )
        await soma.tick_once()  # seeds the fatigue _last_time
        clk.advance(20.0)
        await soma.tick_once()  # integrates e * (20 * scale)
        value = soma._fatigue.value
        await bus.close()
        return value

    slow = await _run(1.0, ManualClock())
    fast = await _run(2.0, ManualClock())
    assert slow > 0.0
    # Same real 20s elapsed, twice the subjective rate → ~twice the fatigue.
    assert fast == pytest.approx(2.0 * slow, rel=1e-6)


# ---------------------------------------------------------------------------
# COGNITIVE: Topos capture cadence (real sleep) scales with time_scale.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_topos_capture_cadence_real_sleep_scales():
    """The capture interval is a subjective cadence: at scale 2.0 the camera
    waits half as long in REAL seconds (samples twice as fast); at 0.5, twice
    as long. The desired-state poll (infra) is unaffected — covered below."""
    from kaine.modules.topos.live import LiveCamera, LiveCameraConfig

    captured: list[float] = []

    async def _fake_wait_for(awaitable, timeout):
        captured.append(timeout)
        # Close the coroutine we were handed (self._stopped.wait()) and raise the
        # timeout so the cadence helper returns as if the interval elapsed.
        awaitable.close()
        raise TimeoutError

    import kaine.modules.topos.live as live_mod

    cfg = LiveCameraConfig(capture_interval_s=2.0)

    async def _real_timeout(scale: float) -> float:
        captured.clear()
        cam = LiveCamera(
            sink=lambda image: None,
            config=cfg,
            entity_clock=EntityClock(scale=scale),
        )
        import asyncio

        original = asyncio.wait_for
        try:
            asyncio.wait_for = _fake_wait_for  # type: ignore[assignment]
            await cam._sleep_capture_interval()
        finally:
            asyncio.wait_for = original
        return captured[0]

    # scale 1.0: real wait == subjective interval (behavior-identical).
    assert await _real_timeout(1.0) == pytest.approx(2.0)
    # scale 2.0: half the real wait (faster sampling).
    assert await _real_timeout(2.0) == pytest.approx(1.0)
    # scale 0.5: twice the real wait (slower sampling).
    assert await _real_timeout(0.5) == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# INFRASTRUCTURE: these timers must NOT scale with time_scale.
# ---------------------------------------------------------------------------


def test_spot_liveness_poll_does_not_scale():
    """The Spot module-supervisor poll/heartbeat-timeout are read straight off
    SpotConfig and never routed through the EntityClock — a watchdog must keep
    real wall-clock cadence even if the mind dilates."""
    from kaine.cycle.spot import SpotConfig

    cfg = SpotConfig.from_section({"poll_interval_s": 1.5, "heartbeat_timeout_s": 9.0})
    # These are plain config floats; there is no clock multiplier anywhere on the
    # path, so the values the watchdog uses are identical regardless of scale.
    assert cfg.poll_interval_s == pytest.approx(1.5)
    assert cfg.heartbeat_timeout_s == pytest.approx(9.0)
    # The Spot source must not reach for the subjective clock at all.
    import inspect

    import kaine.cycle.spot as spot_mod

    assert "EntityClock" not in inspect.getsource(spot_mod)


def test_request_timeout_does_not_scale():
    """A network request timeout (here: the language-organ chat client) is real
    wall-clock seconds — it must not dilate, or a dilated mind would change how
    long it waits on an external service."""
    from kaine.modules.lingua.client import OpenAIChatClient

    client = OpenAIChatClient(base_url="http://localhost:1234/v1", timeout_s=12.0)
    # The configured timeout is a plain real-seconds value, unaffected by any
    # entity time_scale (the client has no EntityClock).
    assert float(client._timeout_s) == pytest.approx(12.0)


# ---------------------------------------------------------------------------
# Single shared clock instance across cycle + every cognitive module.
# ---------------------------------------------------------------------------


def test_build_registry_injects_one_shared_clock(monkeypatch):
    """build_registry constructs ONE EntityClock from [cycle].time_scale, puts
    it on the registry, and injects the SAME instance into every cognitive
    module — so the cycle (which reads registry.entity_clock) and the modules
    cannot desynchronize."""
    pytest.importorskip("fakeredis.aioredis")
    from fakeredis.aioredis import FakeRedis

    from kaine.boot import build_registry
    from kaine.bus.client import AsyncBus
    from kaine.bus.config import BusConfig

    bus = AsyncBus(
        BusConfig(password="x", audit_required=False),
        client=FakeRedis(decode_responses=True),
    )
    config = {
        "cycle": {"time_scale": 2.0},
        "modules": {"soma": True, "thymos": True, "perception": True},
        # inmemory backends so no external services are needed
        "mnemos": {"backend": "inmemory"},
    }
    registry = build_registry(bus, config)

    clock = registry.entity_clock
    assert clock is not None
    assert clock.scale == pytest.approx(2.0)

    # Every cognitive module holds the SAME instance (identity, not a copy).
    assert registry.get("soma")._clock is clock
    assert registry.get("perception")._clock is clock
    # Thymos stores clock.now (a bound method of the shared instance).
    assert registry.get("thymos")._clock == clock.now


def test_build_registry_accepts_an_external_clock():
    """When the caller already has an EntityClock, build_registry uses THAT one
    (so the cycle and registry can be built in either order and still share a
    single instance)."""
    pytest.importorskip("fakeredis.aioredis")
    from fakeredis.aioredis import FakeRedis

    from kaine.boot import build_registry
    from kaine.bus.client import AsyncBus
    from kaine.bus.config import BusConfig

    bus = AsyncBus(
        BusConfig(password="x", audit_required=False),
        client=FakeRedis(decode_responses=True),
    )
    external = EntityClock(scale=0.5)
    registry = build_registry(
        bus,
        {"modules": {"soma": True}, "cycle": {"time_scale": 9.9}},
        entity_clock=external,
    )
    # The injected clock wins over [cycle].time_scale.
    assert registry.entity_clock is external
    assert registry.get("soma")._clock is external
