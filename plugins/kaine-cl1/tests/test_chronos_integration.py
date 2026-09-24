# SPDX-License-Identifier: LicenseRef-CAL-0.2
"""Live integration: the real KAINE `Chronos` module running its forward model on
the substrate, over a real (fake-backed) bus.

Skips cleanly where the `kaine` stack (and `fakeredis`) is not installed,
so the sim-only suite still runs anywhere. Where kaine IS installed (the build
machine), this proves the conversion is pure injection: stock Chronos +
`WetwareTimingModel` publishes the same `chronos.out` contract as silicon.
"""
from __future__ import annotations

import math
import os

import pytest

os.environ.setdefault("CL_SDK_ACCELERATED_TIME", "1")
os.environ.setdefault("CL_SDK_VISUALISATION", "0")

pytest.importorskip("kaine", reason="requires the local kaine stack")
pytest.importorskip("fakeredis", reason="requires fakeredis for the in-memory bus")

import cl.sim as clsim  # noqa: E402
import fakeredis.aioredis  # noqa: E402
from kaine_cl1.boot import wetware_injection  # noqa: E402
from kaine_cl1.substrate.broker import SubstrateBroker  # noqa: E402
from kaine_cl1.substrate.session import SubstrateConfig, SubstrateSession  # noqa: E402

from kaine.bus.client import AsyncBus  # noqa: E402
from kaine.bus.config import BusConfig  # noqa: E402
from kaine.cycle.types import WorkspaceSnapshot  # noqa: E402
from kaine.modules.chronos.anomaly import RollingZScoreAnomaly  # noqa: E402
from kaine.modules.chronos.featurizer import SnapshotFeaturizer  # noqa: E402
from kaine.modules.chronos.module import Chronos  # noqa: E402
from kaine.modules.chronos.rumination import RecurrenceRuminationDetector  # noqa: E402


class _SiliconNetwork:
    """A silicon stand-in with the same interface KAINE's own tests use for the
    `network=` seam — for schema comparison against the wetware backend."""

    def __init__(self, units: int = 8):
        self.units = units

    def tick(self, feature_vec):
        return [0.5] * self.units


def _bus():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return AsyncBus(BusConfig(password="x", audit_required=False), client=client)


def _chronos(bus, network):
    return Chronos(
        bus,
        featurizer=SnapshotFeaturizer(clock=lambda: 0.0),
        network=network,
        anomaly=RollingZScoreAnomaly(window=4),
        rumination=RecurrenceRuminationDetector(window=4, threshold=4),
    )


def _open_substrate(nesting=6, territory=8):
    clsim.set_simulator_data_source(
        "kaine_cl1.substrate.sources:make_reference_culture",
        config={"seed": 7, "baseline_hz": 2.0, "evoked_spikes": 16, "response_ms": 20.0},
    )
    s = SubstrateSession(SubstrateConfig(accelerated_time=True, ticks_per_second=100))
    s.open()
    b = SubstrateBroker(channel_count=64, ticks_per_second=100, nesting_factor=nesting)
    terr = b.allocate("chronos", territory)
    b.open(s.neurons)
    return s, b, terr


async def _run_wetware_chronos(ticks=4):
    s, b, terr = _open_substrate()
    try:
        kwarg, net = wetware_injection("chronos", b, terr)  # ("network", WetwareTimingModel)
        assert kwarg == "network"
        bus = _bus()
        chronos = _chronos(bus, net)
        assert chronos.has_network is True
        for t in range(ticks):
            await chronos.on_workspace(
                WorkspaceSnapshot(tick_index=t, selected_events=[], inhibited=False)
            )
        entries = await bus.read("chronos.out", last_id="0")
        await bus.close()
        return [ev for _, ev in entries]
    finally:
        s.close()
        clsim.clear_simulator_data_source()


async def _run_silicon_chronos(ticks=4):
    bus = _bus()
    chronos = _chronos(bus, _SiliconNetwork(units=8))
    for t in range(ticks):
        await chronos.on_workspace(
            WorkspaceSnapshot(tick_index=t, selected_events=[], inhibited=False)
        )
    entries = await bus.read("chronos.out", last_id="0")
    await bus.close()
    return [ev for _, ev in entries]


async def test_wetware_network_injects_into_real_chronos():
    events = await _run_wetware_chronos(ticks=4)
    assert len(events) == 4
    assert all(ev.type == "chronos.report" for ev in events)
    # the biological forward model produced a real, finite temporal signal
    for ev in events:
        err = ev.payload["temporal_prediction_error"]
        assert isinstance(err, (int, float))
        assert not math.isnan(err)


async def test_event_schema_matches_silicon():
    wet = await _run_wetware_chronos(ticks=3)
    sil = await _run_silicon_chronos(ticks=3)
    assert {e.type for e in wet} == {e.type for e in sil} == {"chronos.report"}
    # The wetware backend does not change Chronos' published event contract.
    assert set(wet[0].payload.keys()) == set(sil[0].payload.keys())
