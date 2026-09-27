# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for entity-clock injection into the remaining cognitive timers."""

from __future__ import annotations

import asyncio
import json
import math
from datetime import datetime, timezone
from typing import Any

import pytest

import kaine.modules.vox.module as _vox_module
from kaine.boot import construct_module
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.types import WorkspaceSnapshot
from kaine.entity_clock import EntityClock
from kaine.modules.chronos.featurizer import SnapshotFeaturizer
from kaine.modules.chronos.module import Chronos
from kaine.modules.soma.module import Soma
from kaine.modules.thymos.state import DimensionalState
from kaine.modules.vox import FakePlayer, FakeTTSClient, Vox


class Ticker:
    """Injected monotonic source whose value the test controls."""

    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


class FakeReader:
    def __init__(self) -> None:
        self.latency_samples: list[float] = []

    def update_cycle_latency_sample(self, latency: float) -> None:
        self.latency_samples.append(latency)


def _bus() -> AsyncBus:
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    return AsyncBus(BusConfig(password="x", audit_required=False), client=client)


async def _drive_one_cycle_tick(
    bus: AsyncBus, soma: Soma, reader: FakeReader, wall_duration_ms: float
) -> None:
    """Publish a single cycle.tick and run Soma's consumer until it is processed."""
    await bus.client.xadd(
        soma._cycle_stream,
        {
            "source": "cycle",
            "type": "cycle.tick",
            "salience": "0.1",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "causal_parent": "",
            "payload": json.dumps({"wall_duration_ms": wall_duration_ms}),
        },
    )

    processed = asyncio.get_running_loop().create_future()
    original_update = reader.update_cycle_latency_sample

    def _update(latency: float) -> None:
        original_update(latency)
        if not processed.done():
            processed.set_result(None)

    soma._reader.update_cycle_latency_sample = _update  # type: ignore[method-assign]

    task = asyncio.create_task(soma._cycle_consumer_loop())
    await asyncio.wait_for(processed, timeout=1.0)
    soma._stopped.set()
    await task


@pytest.mark.parametrize("scale, expected_delta", [(1.0, 2.0), (0.5, 1.0)])
def test_chronos_delta_and_interaction_follow_entity_clock(scale, expected_delta):
    ticker = Ticker()
    clock = EntityClock(scale=scale, monotonic=ticker)
    bus = _bus()
    try:
        chronos = Chronos(
            bus,
            featurizer=SnapshotFeaturizer(clock=clock.now),
            entity_clock=clock,
        )

        snap = WorkspaceSnapshot(tick_index=0, selected_events=[], inhibited=False)
        chronos._featurizer.featurize(snap)
        ticker.advance(2.0)
        vec = chronos._featurizer.featurize(snap)
        delta = math.expm1(vec[20])
        assert abs(delta - expected_delta) < 1e-9

        chronos._last_interaction_at = chronos._clock()
        ticker.advance(2.0)
        assert abs(chronos._time_since_last_interaction_s() - expected_delta) < 1e-9
    finally:
        asyncio.run(bus.close())


def test_chronos_explicit_clock_wins_over_entity_clock():
    ticker = Ticker()
    clock = EntityClock(scale=0.5, monotonic=ticker)
    bus = _bus()
    try:
        chronos = Chronos(bus, entity_clock=clock, clock=lambda: 42.0)
        assert chronos._clock() == 42.0
        assert chronos._featurizer._clock() == 42.0
    finally:
        asyncio.run(bus.close())


@pytest.mark.parametrize("scale, expected_elapsed", [(1.0, 2.0), (0.5, 1.0)])
def test_vox_mirroring_decay_follows_entity_clock(scale, expected_elapsed, tmp_path):
    ticker = Ticker()
    clock = EntityClock(scale=scale, monotonic=ticker)
    bus = _bus()
    try:
        vox = Vox(
            bus,
            tts_client=FakeTTSClient(canned_audio=b"WAV-FAKE-DATA-1234"),
            player=FakePlayer(),
            sink_path=tmp_path / "vox",
            predefined_voice_id="default_sample.wav",
            entity_clock=clock,
            mirroring_enabled=True,
            mirror_strength=0.3,
            mirror_decay_s=10.0,
        )

        # Record a prosody sample as if an audition.prosody event just arrived.
        vox._latest_prosody = {"f0_mean_hz": 110.0}
        vox._latest_prosody_ts = vox._clock.now()

        ticker.advance(2.0)

        captured: list[float] = []
        original_blend = _vox_module.blend_prosody

        def fake_blend(params: Any, prosody: Any, strength: float) -> Any:
            captured.append(strength)
            return params

        _vox_module.blend_prosody = fake_blend
        try:
            vox._params_for(DimensionalState())
        finally:
            _vox_module.blend_prosody = original_blend

        # Linear decay over the 10 s window (see mirroring.decayed_strength).
        expected_strength = 0.3 * (1.0 - expected_elapsed / 10.0)
        assert len(captured) == 1
        assert abs(captured[0] - expected_strength) < 1e-6
    finally:
        asyncio.run(bus.close())


@pytest.mark.parametrize("scale, expected_latency", [(1.0, 300.0), (0.5, 150.0)])
def test_soma_cycle_latency_scaled_to_subjective_time(scale, expected_latency):
    ticker = Ticker()
    clock = EntityClock(scale=scale, monotonic=ticker)
    bus = _bus()
    try:
        reader = FakeReader()
        soma = Soma(bus, reader=reader, entity_clock=clock)

        asyncio.run(_drive_one_cycle_tick(bus, soma, reader, wall_duration_ms=300))
        assert reader.latency_samples == [expected_latency]
    finally:
        asyncio.run(bus.close())


def test_boot_passes_registry_entity_clock_to_chronos_and_vox():
    bus = _bus()
    try:
        ticker = Ticker()
        clock = EntityClock(scale=0.5, monotonic=ticker)

        original_build_player = _vox_module.build_player
        original_chatterbox_client = _vox_module.ChatterboxClient
        _vox_module.build_player = lambda **kw: FakePlayer()
        _vox_module.ChatterboxClient = lambda **kw: FakeTTSClient()

        try:
            chronos = construct_module(
                "chronos",
                bus,
                {"chronos": {}},
                registry={},
                entity_clock=clock,
            )
            assert chronos._clock() == clock.now()
            assert chronos._clock.__self__ is clock
            assert chronos._featurizer._clock() == clock.now()

            vox = construct_module(
                "vox",
                bus,
                {"vox": {}},
                registry={},
                entity_clock=clock,
            )
            assert vox._clock is clock
        finally:
            _vox_module.build_player = original_build_player
            _vox_module.ChatterboxClient = original_chatterbox_client
    finally:
        asyncio.run(bus.close())
