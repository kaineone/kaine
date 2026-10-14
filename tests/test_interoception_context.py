# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import math
from datetime import datetime, timezone

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.interoception import AlertResult, Interoception
from kaine.modules.interoception.forward import SubstrateForwardModel


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


def test_interoception_null_error_recorded() -> None:
    m = SubstrateForwardModel(feature_dim=8, units=16, seed=5, context_dim=24)
    ctx = [0.5] * 24

    m.step([0.1] * 8, context=ctx, null_context=ctx)
    second = m.step([0.2] * 8, context=ctx, null_context=ctx)

    assert m.last_scored_had_context is True
    assert m.last_null_error == pytest.approx(second)


@pytest.mark.asyncio
async def test_interoception_reports_context_gain(bus: AsyncBus) -> None:
    interoception = Interoception(
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
                    source="vision",
                    type="vision.report",
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
    await interoception.on_workspace(snapshot)

    payload = None
    for _ in range(3):
        payload = await interoception.tick_once()

    assert payload is not None
    assert "context_gain" in payload
    # By the third report the scored prediction was formed with a context.
    assert isinstance(payload["context_gain"], float)
    assert math.isfinite(payload["context_gain"])
    assert "context_age_s" in payload
    assert isinstance(payload["context_age_s"], float)
    assert payload["context_age_s"] >= 0.0


@pytest.mark.asyncio
async def test_interoception_gain_is_zero_when_the_context_carries_nothing(bus: AsyncBus) -> None:
    interoception = Interoception(
        bus,
        reader=FakeMetricsReader({"cpu_percent": 10.0, "ram_percent": 20.0}),
        detector=NeverAlertDetector(),
    )

    for i in range(4):
        snapshot = WorkspaceSnapshot(
            tick_index=i,
            selected_events=[
                (
                    f"{i}-0",
                    Event(
                        source="vision",
                        type="vision.report",
                        payload={"k": 1},
                        salience=0.5,
                        timestamp=datetime.now(timezone.utc),
                    ),
                )
            ],
            inhibited=False,
            salience_scores={f"{i}-0": 0.5},
            metadata={"access_threshold": 0.35},
        )
        await interoception.on_workspace(snapshot)
        payload = await interoception.tick_once()

    assert payload is not None
    assert payload["context_gain"] == 0.0
    assert payload["null_prediction_error"] == payload["prediction_error"]
    assert payload["mean_prediction_error"] > 0.0


def test_skipped_reading_reports_no_gain() -> None:
    m = SubstrateForwardModel(feature_dim=8, units=16, seed=5, context_dim=24)
    ctx = [0.5] * 24
    m.step([0.1] * 8, context=ctx, null_context=ctx)
    m.step([0.2] * 8, context=ctx, null_context=ctx)
    assert m.last_null_error is not None
    err = m.step([float("nan")] * 8, context=ctx, null_context=ctx)
    assert err == 0.0
    assert m.last_error_defined is False  # skipped input has no defined error
    assert m.last_null_error is None
    assert m.last_scored_had_context is False
    assert m.last_reading_skipped is True
    err2 = m.step([0.3] * 8, context=ctx, null_context=ctx)
    assert err2 == 0.0
    assert m.last_error_defined is False  # first finite step after a skip has no prediction to score
    assert m.last_null_error is None
    assert m.last_scored_had_context is False
    assert m.last_reading_skipped is False
    m.step([0.4] * 8, context=ctx, null_context=ctx)
    assert m.last_error_defined is True  # second finite step after a skip is scored
    assert m.last_null_error is not None


@pytest.mark.asyncio
async def test_interoception_skip_publishes_no_gain_and_leaves_the_window(
    bus: AsyncBus, monkeypatch: pytest.MonkeyPatch
) -> None:
    interoception = Interoception(
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
                    source="vision",
                    type="vision.report",
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
    await interoception.on_workspace(snapshot)

    await interoception.tick_once()
    await interoception.tick_once()
    p3 = await interoception.tick_once()
    assert isinstance(p3["context_gain"], float)

    window_before = list(interoception._prediction_error_window)

    monkeypatch.setattr(
        "kaine.modules.interoception.module.metrics_to_feature_vector",
        lambda *a, **k: [float("nan")] * 8,
    )
    p4 = await interoception.tick_once()
    monkeypatch.undo()

    assert p4["context_gain"] is None
    assert p4["null_prediction_error"] is None
    assert p4["mean_prediction_error"] is None
    assert p4["prediction_error"] is None  # undefined error after skip
    assert list(interoception._prediction_error_window) == window_before

    p5 = await interoception.tick_once()
    assert p5["context_gain"] is None
    assert p5["null_prediction_error"] is None
    assert p5["prediction_error"] is None  # first finite step after a skip is unscored
    assert list(interoception._prediction_error_window) == window_before  # window still unchanged

    p6 = await interoception.tick_once()
    assert isinstance(p6["context_gain"], float)
    assert isinstance(p6["prediction_error"], float)  # second finite step is scored
    assert list(interoception._prediction_error_window) == (
        window_before + [p6["prediction_error"]]
    )[-interoception._prediction_error_window.maxlen:]


@pytest.mark.asyncio
async def test_interoception_report_carries_the_paired_evaluations(bus: AsyncBus) -> None:
    interoception = Interoception(
        bus,
        reader=FakeMetricsReader({"cpu_percent": 10.0, "ram_percent": 20.0}),
        detector=NeverAlertDetector(),
    )

    vision_entry = (
        "1-0",
        Event(
            source="vision",
            type="vision.report",
            payload={"k": 1},
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        ),
    )
    await interoception.on_workspace(
        WorkspaceSnapshot(
            tick_index=1,
            selected_events=[vision_entry],
            inhibited=False,
            salience_scores={vision_entry[0]: 0.5},
            metadata={"access_threshold": 0.35},
        )
    )
    await interoception.tick_once()

    affect_entry = (
        "2-0",
        Event(
            source="affect",
            type="affect.report",
            payload={"k": 1},
            salience=0.75,
            timestamp=datetime.now(timezone.utc),
        ),
    )
    await interoception.on_workspace(
        WorkspaceSnapshot(
            tick_index=2,
            selected_events=[affect_entry],
            inhibited=False,
            salience_scores={affect_entry[0]: 0.75},
            metadata={"access_threshold": 0.35},
        )
    )

    payload = None
    for _ in range(3):
        payload = await interoception.tick_once()

    assert payload is not None
    assert isinstance(payload["null_prediction_error"], float)
    assert isinstance(payload["mean_prediction_error"], float)
    assert payload["context_gain"] == pytest.approx(
        (payload["null_prediction_error"] - payload["prediction_error"])
        / payload["mean_prediction_error"]
    )
