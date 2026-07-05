# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.soma import (
    AlertResult,
    Soma,
    ThresholdAnomalyDetector,
)
from kaine.modules.soma.reader import MetricsReader


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


class AlwaysAlertDetector:
    def evaluate(self, metrics: dict[str, float]) -> AlertResult:
        return AlertResult(keys=("forced",))


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


@pytest.mark.asyncio
async def test_metricsreader_protocol_satisfied():
    reader = FakeMetricsReader()
    assert isinstance(reader, MetricsReader)


@pytest.mark.asyncio
async def test_tick_once_publishes_baseline_report(bus: AsyncBus):
    reader = FakeMetricsReader({"cpu_percent": 10.0, "ram_percent": 20.0})
    soma = Soma(bus, reader=reader, detector=NeverAlertDetector())
    payload = await soma.tick_once()
    assert payload["alerts"] == []
    assert payload["wellness"] == pytest.approx(0.85)
    entries = await bus.read("soma.out", last_id="0")
    # The developmental warm-up (enabled by default) emits a soma.warmup.started
    # marker before the first report; select the report by type.
    reports = [ev for _, ev in entries if ev.type == "soma.report"]
    assert len(reports) == 1
    event = reports[0]
    assert event.salience == pytest.approx(soma._baseline_salience)
    assert event.payload["metrics"] == {"cpu_percent": 10.0, "ram_percent": 20.0}


@pytest.mark.asyncio
async def test_alert_raises_salience(bus: AsyncBus):
    reader = FakeMetricsReader({"cpu_percent": 95.0})
    detector = ThresholdAnomalyDetector({"cpu_percent": 90.0})
    soma = Soma(bus, reader=reader, detector=detector)
    payload = await soma.tick_once()
    assert payload["alerts"] == ["cpu_percent"]
    entries = await bus.read("soma.out", last_id="0")
    # Select the report past the warm-up marker (enabled by default).
    event = next(ev for _, ev in entries if ev.type == "soma.report")
    assert event.salience == pytest.approx(soma._alert_salience)
    assert event.payload["alerts"] == ["cpu_percent"]


@pytest.mark.asyncio
async def test_cycle_consumer_feeds_latency_into_reader(bus: AsyncBus):
    reader = FakeMetricsReader({"cpu_percent": 10.0})
    soma = Soma(bus, reader=reader, detector=NeverAlertDetector())

    # Pretend the cycle published three tick events.
    for ms in (100.0, 200.0, 300.0):
        await bus.publish(
            Event(
                source="cycle",
                type="cycle.tick",
                payload={"wall_duration_ms": ms},
                salience=0.05,
                timestamp=datetime.now(timezone.utc),
            )
        )

    await soma.initialize()
    # Give the cycle consumer task a moment to drain cycle.out.
    for _ in range(50):
        if reader.latencies:
            break
        await asyncio.sleep(0.01)
    await soma.shutdown()
    assert reader.latencies == [100.0, 200.0, 300.0]


@pytest.mark.asyncio
async def test_initialize_calls_reader_initialize(bus: AsyncBus):
    reader = FakeMetricsReader()
    soma = Soma(bus, reader=reader, detector=NeverAlertDetector())
    await soma.initialize()
    try:
        assert reader.initialized is True
    finally:
        await soma.shutdown()
    assert reader.shutdown_called is True


@pytest.mark.asyncio
async def test_custom_detector_substitutes(bus: AsyncBus):
    reader = FakeMetricsReader()
    soma = Soma(bus, reader=reader, detector=AlwaysAlertDetector())
    payload = await soma.tick_once()
    assert payload["alerts"] == ["forced"]


@pytest.mark.asyncio
async def test_produce_loop_emits_multiple_reports(bus: AsyncBus):
    reader = FakeMetricsReader({"cpu_percent": 5.0})
    soma = Soma(
        bus,
        reader=reader,
        detector=NeverAlertDetector(),
        read_interval_s=0.02,
    )
    await soma.initialize()
    try:
        await asyncio.sleep(0.1)
    finally:
        await soma.shutdown()
    entries = await bus.read("soma.out", last_id="0", count=100)
    assert len(entries) >= 2


@pytest.mark.asyncio
async def test_invalid_construction_rejected(bus: AsyncBus):
    with pytest.raises(ValueError):
        Soma(bus, reader=FakeMetricsReader(), read_interval_s=0.0)
    with pytest.raises(ValueError):
        Soma(bus, reader=FakeMetricsReader(), baseline_salience=1.5)
    with pytest.raises(ValueError):
        Soma(bus, reader=FakeMetricsReader(), alert_salience=-0.1)


@pytest.mark.asyncio
async def test_serialize_roundtrips_cursor(bus: AsyncBus):
    reader = FakeMetricsReader()
    soma = Soma(bus, reader=reader, detector=NeverAlertDetector())
    soma._cycle_cursor = "12345-0"
    state = soma.serialize()
    fresh = Soma(bus, reader=FakeMetricsReader(), detector=NeverAlertDetector())
    fresh.deserialize(state)
    assert fresh._cycle_cursor == "12345-0"


# ---------------------------------------------------------------------------
# Predictive interoception additions (soma-forward-model-fatigue)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tick_once_report_carries_prediction_error(bus: AsyncBus):
    pytest.importorskip("torch")
    reader = FakeMetricsReader({"cpu_percent": 10.0, "ram_percent": 20.0})
    soma = Soma(bus, reader=reader, detector=NeverAlertDetector())
    payload = await soma.tick_once()
    assert "prediction_error" in payload
    assert isinstance(payload["prediction_error"], float)


@pytest.mark.asyncio
async def test_tick_once_report_carries_fatigue(bus: AsyncBus):
    pytest.importorskip("torch")
    reader = FakeMetricsReader({"cpu_percent": 10.0, "ram_percent": 20.0})
    soma = Soma(bus, reader=reader, detector=NeverAlertDetector())
    payload = await soma.tick_once()
    assert "fatigue_value" in payload
    assert "fatigue_threshold" in payload
    assert isinstance(payload["fatigue_value"], float)
    assert isinstance(payload["fatigue_threshold"], float)


@pytest.mark.asyncio
async def test_serialize_roundtrip_includes_forward_model_and_fatigue(bus: AsyncBus):
    pytest.importorskip("torch")
    reader = FakeMetricsReader({"cpu_percent": 50.0, "ram_percent": 60.0})
    soma = Soma(bus, reader=reader, detector=NeverAlertDetector())
    # Do a few ticks to give the forward model some state.
    for _ in range(5):
        await soma.tick_once()
    # Manually set a non-zero fatigue value.
    soma._fatigue._value = 17.5

    state = soma.serialize()
    assert "forward_model" in state
    assert "fatigue" in state

    fresh = Soma(bus, reader=FakeMetricsReader(), detector=NeverAlertDetector())
    fresh.deserialize(state)

    # Fatigue value should be restored.
    assert fresh._fatigue.value == pytest.approx(17.5)

    # Forward model readout weights should match after restore. The CfC
    # reservoir itself is a frozen, independently-seeded random projection
    # that is intentionally never serialised (mirroring Chronos's
    # CfCNetwork) — `soma` and `fresh` have DIFFERENT reservoirs, so only
    # the persisted readout weights (the learned, adapting part) are
    # expected to round-trip exactly.
    orig_sd = soma._forward_model.state_dict()
    fresh_sd = fresh._forward_model.state_dict()
    assert orig_sd["weight"] == fresh_sd["weight"]
    assert orig_sd["bias"] == fresh_sd["bias"]
