# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from datetime import datetime, timezone

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.soma import AlertResult, Soma
from kaine.modules.soma.forward import SubstrateForwardModel


class FakeMetricsReader:
    def __init__(self, metrics: dict[str, float] | None = None) -> None:
        self._metrics = metrics or {"cpu_percent": 10.0, "ram_percent": 20.0}
        self.latencies: list[float] = []
        self.initialized = False
        self.shutdown_called = False

    async def initialize(self) -> None:
        self.initialized = True

    async def shutdown(self) -> None:
        self.shutdown_called = True

    async def read_metrics(self) -> dict[str, float]:
        out = dict(self._metrics)
        if self.latencies:
            out["cycle_latency_avg_ms"] = sum(self.latencies) / len(self.latencies)
        return out

    def update_cycle_latency_sample(self, wall_duration_ms: float) -> None:
        self.latencies.append(float(wall_duration_ms))


class NeverAlertDetector:
    def evaluate(self, metrics: dict[str, float]) -> AlertResult:
        return AlertResult()


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def test_legacy_readout_restores_with_zero_context_weights() -> None:
    old = SubstrateForwardModel(feature_dim=8, units=16, seed=5)
    new = SubstrateForwardModel(feature_dim=8, units=16, seed=5, context_dim=24)
    new.load_state_dict(old.state_dict())

    f = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
    assert new.predict(f, context=[0.5] * 24) == pytest.approx(old.predict(f))


def test_soma_null_error_recorded() -> None:
    m = SubstrateForwardModel(feature_dim=8, units=16, seed=5, context_dim=24)
    ctx = [0.5] * 24

    m.step([0.1] * 8, context=ctx, null_context=ctx)
    second = m.step([0.2] * 8, context=ctx, null_context=ctx)

    assert m.last_scored_had_context is True
    assert m.last_null_error == pytest.approx(second)


@pytest.mark.asyncio
async def test_soma_reports_context_gain(bus: AsyncBus) -> None:
    soma = Soma(
        bus,
        reader=FakeMetricsReader({"cpu_percent": 10.0, "ram_percent": 20.0}),
        detector=NeverAlertDetector(),
    )

    snapshot = WorkspaceSnapshot(
        tick_index=1,
        selected_events=[
            (
                "1-0",
                Event(
                    source="topos",
                    type="topos.report",
                    payload={"k": 1},
                    salience=0.7,
                    timestamp=datetime.now(timezone.utc),
                ),
            )
        ],
        inhibited=False,
        salience_scores={"1-0": 0.5},
        metadata={"access_threshold": 0.35},
    )
    await soma.on_workspace(snapshot)

    payload = None
    for _ in range(3):
        payload = await soma.tick_once()

    assert payload is not None
    assert "context_gain" in payload
    assert "context_age_s" in payload
    assert isinstance(payload["context_age_s"], float)
    assert payload["context_age_s"] >= 0.0
