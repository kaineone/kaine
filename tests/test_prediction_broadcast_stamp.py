# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the broadcast-context stamp that labels scored predictions."""

from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np
import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.audition import Audition, FakeEmotionClassifier, FakeSTTClient
from kaine.modules.audition.acoustic import FakeAcousticEncoder
from kaine.modules.context import CONTEXT_DIM, BroadcastContext
from kaine.modules.soma.detector import AlertResult
from kaine.modules.soma.forward import SubstrateForwardModel
from kaine.modules.soma.module import Soma
from kaine.modules.topos import Topos
from kaine.modules.topos.forward import LatentForwardModel


class _MutableClock:
    """Callable and entity-clock-like clock for deterministic ageing."""

    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def now(self) -> float:
        return self.t


def _bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    return AsyncBus(BusConfig(password="x", audit_required=False), client=client)


def _workspace(
    tick_index: int,
    inhibited: bool,
    score: float,
    published_at: float | None = None,
) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(
        tick_index=tick_index,
        selected_events=[
            (
                "1-0",
                Event(
                    source="topos",
                    type="topos.report",
                    payload={"k": 1},
                    salience=0.7 if not inhibited else 0.1,
                    timestamp=datetime.now(timezone.utc),
                ),
            )
        ],
        inhibited=inhibited,
        salience_scores={"1-0": score},
        metadata={"access_threshold": 0.35},
        published_at=published_at,
    )


def _typed_payloads(events, event_type):
    """Return payloads for events of a specific type."""
    out = []
    for ev in events:
        if isinstance(ev, tuple):
            ev = ev[-1]
        if getattr(ev, "type", None) == event_type and hasattr(ev, "payload"):
            out.append(ev.payload)
    return out


def _tone(freq: float, seconds: float = 0.2, amp: float = 0.3, sr: int = 16000) -> bytes:
    samples = np.arange(int(sr * seconds))
    wave = (amp * np.sin(2.0 * np.pi * freq * samples / sr) * 32767).astype(np.int16)
    return wave.tobytes()


class FakeMetricsReader:
    def __init__(self, metrics: dict[str, float] | None = None) -> None:
        self._metrics = metrics or {"cpu_percent": 10.0, "ram_percent": 20.0}
        self.initialized = False
        self.shutdown_called = False

    async def initialize(self) -> None:
        self.initialized = True

    async def shutdown(self) -> None:
        self.shutdown_called = True

    async def read_metrics(self) -> dict[str, float]:
        return dict(self._metrics)

    def update_cycle_latency_sample(self, wall_duration_ms: float) -> None:
        pass


class NeverAlertDetector:
    def evaluate(self, metrics: dict[str, float]) -> AlertResult:  # noqa: ARG002
        return AlertResult()


def test_context_last_reading_before_any_broadcast() -> None:
    clock = _MutableClock(1.0)
    ctx = BroadcastContext(clock)
    vec, null = ctx.context_and_null(("topos",))
    assert vec is None
    assert null is None
    assert ctx.last_reading == (None, None)


def test_context_last_reading_after_inhibited_broadcast() -> None:
    clock = _MutableClock(5.0)
    ctx = BroadcastContext(clock)
    snapshot = WorkspaceSnapshot(
        tick_index=3,
        selected_events=[],
        inhibited=True,
        salience_scores={},
        metadata={},
    )
    ctx.observe(snapshot)
    vec, null = ctx.context_and_null(("topos",))
    assert vec is None
    assert null is None
    assert ctx.last_reading == (3, None)


def test_context_last_reading_after_accessed_then_inhibited() -> None:
    clock = _MutableClock(10.0)
    ctx = BroadcastContext(clock)
    accessed = WorkspaceSnapshot(
        tick_index=7,
        selected_events=[
            (
                "1-0",
                Event(
                    source="topos",
                    type="topos.report",
                    payload={"k": 1},
                    salience=0.6,
                    timestamp=datetime.now(timezone.utc),
                ),
            )
        ],
        inhibited=False,
        salience_scores={"1-0": 0.5},
        metadata={"access_threshold": 0.35},
        published_at=10.0,
    )
    ctx.observe(accessed)
    clock.t = 12.5
    inhibited = WorkspaceSnapshot(
        tick_index=8,
        selected_events=[],
        inhibited=True,
        salience_scores={},
        metadata={},
    )
    ctx.observe(inhibited)
    vec, null = ctx.context_and_null(("topos",))
    assert vec is not None
    assert ctx.last_reading == (8, 2.5)
    assert vec[20] == pytest.approx(math.log1p(2.5))


@pytest.mark.asyncio
async def test_soma_prediction_stamp_end_to_end() -> None:
    bus = _bus()
    try:
        clock = _MutableClock(0.0)
        soma = Soma(
            bus,
            reader=FakeMetricsReader({"cpu_percent": 10.0, "ram_percent": 20.0}),
            detector=NeverAlertDetector(),
            entity_clock=clock,
        )
        soma._forward_model = SubstrateForwardModel(
            feature_dim=8,
            units=16,
            seed=5,
            context_dim=CONTEXT_DIM,
        )

        clock.t = 10.0
        await soma.on_workspace(_workspace(7, False, 0.5, published_at=10.0))
        clock.t = 11.0
        await soma.tick_once()
        await soma.on_workspace(_workspace(8, True, 0.1))
        clock.t = 13.0
        await soma.tick_once()
        clock.t = 14.0
        await soma.tick_once()

        events = await bus.read("soma.out", last_id="0")
        reports = _typed_payloads(events, "soma.report")
        assert len(reports) == 3
        assert reports[0]["prediction_broadcast_tick"] is None
        assert reports[0]["prediction_context_age_s"] is None
        assert reports[1]["prediction_broadcast_tick"] == 7
        assert reports[1]["prediction_context_age_s"] == pytest.approx(1.0)
        assert reports[2]["prediction_broadcast_tick"] == 8
        assert reports[2]["prediction_context_age_s"] == pytest.approx(3.0)
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_audition_prediction_stamp_end_to_end() -> None:
    bus = _bus()
    try:
        clock = _MutableClock(0.0)
        audition = Audition(
            bus,
            stt_client=FakeSTTClient(responses=["x"]),
            emotion_classifier=FakeEmotionClassifier(),
            stt_model="fake-stt",
            general_audition=True,
            acoustic_encoder=FakeAcousticEncoder(embedding_dim=8),
            entity_clock=clock,
        )
        await audition.initialize()

        clock.t = 10.0
        await audition.on_workspace(_workspace(7, False, 0.5, published_at=10.0))
        clock.t = 11.0
        await audition.process_audio(_tone(440), sample_rate=16000)
        await audition.on_workspace(_workspace(8, True, 0.1))
        clock.t = 13.0
        await audition.process_audio(_tone(490), sample_rate=16000)
        clock.t = 14.0
        await audition.process_audio(_tone(540), sample_rate=16000)

        events = await bus.read("audition.out", last_id="0")
        reports = _typed_payloads(events, "audition.perception")
        assert len(reports) == 3
        assert reports[0]["prediction_broadcast_tick"] is None
        assert reports[0]["prediction_context_age_s"] is None
        assert reports[1]["prediction_broadcast_tick"] == 7
        assert reports[1]["prediction_context_age_s"] == pytest.approx(1.0)
        assert reports[2]["prediction_broadcast_tick"] == 8
        assert reports[2]["prediction_context_age_s"] == pytest.approx(3.0)
    finally:
        await audition.shutdown()
        await bus.close()


class _SkipsOnSecond:
    model_id = "fake/skips-second"
    latent_dim = 4
    clip_len = 1

    def __init__(self) -> None:
        self._calls = 0

    async def load(self):
        return None

    async def shutdown(self):
        return None

    async def encode(self, image):  # noqa: ARG002
        self._calls += 1
        if self._calls == 2:
            return [float("nan")] * 4
        return [0.1, 0.2, 0.3, 0.4]

    async def encode_clip(self, frames):
        return await self.encode(frames[-1])


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


@pytest.mark.asyncio
async def test_topos_skip_clears_prediction_stamp(bus) -> None:
    clock = _MutableClock(100.0)
    topos = Topos(bus, encoder=_SkipsOnSecond(), forward_prediction=True, entity_clock=clock)
    topos._forward_model = LatentForwardModel(
        latent_dim=4, units=8, context_dim=24, seed=4
    )

    snapshot = WorkspaceSnapshot(
        tick_index=7,
        selected_events=[
            (
                "1-0",
                Event(
                    source="soma",
                    type="soma.report",
                    payload={"k": 1},
                    salience=0.6,
                    timestamp=datetime.now(timezone.utc),
                ),
            )
        ],
        inhibited=False,
        salience_scores={"1-0": 0.5},
        metadata={"access_threshold": 0.35},
    )
    await topos.on_workspace(snapshot)

    for _ in range(4):
        await topos.process_frame(None)

    entries = await bus.read("topos.out", last_id="0")
    reports = _typed_payloads(entries, "topos.report")
    assert len(reports) == 4
    assert reports[2]["prediction_broadcast_tick"] is None
    assert reports[3]["prediction_broadcast_tick"] == 7


@pytest.mark.parametrize("event_type", ["soma.report", "topos.report", "audition.perception"])
def test_research_observer_copies_prediction_stamp(event_type: str) -> None:
    from kaine.evaluation.observers.research_event_observer import _apply_taxonomy_fields

    payload = {
        "prediction_broadcast_tick": 7,
        "prediction_context_age_s": 2.5,
    }
    result = _apply_taxonomy_fields(event_type, payload, {})
    assert result["prediction_broadcast_tick"] == 7
    assert result["prediction_context_age_s"] == 2.5


@pytest.mark.parametrize("event_type", ["soma.report", "topos.report", "audition.perception"])
@pytest.mark.parametrize("field", ["prediction_broadcast_tick", "prediction_context_age_s"])
def test_log_schema_bounds_prediction_stamp(event_type: str, field: str) -> None:
    from kaine.experiment.log_schema import NONNEG, _bound_for

    assert _bound_for(event_type, field) == NONNEG
