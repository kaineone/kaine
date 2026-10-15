# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests that the interoception and audition modules' reports carry entity time and wakefulness."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.audition import Audition, FakeEmotionClassifier, FakeSTTClient
from kaine.modules.audition.acoustic import FakeAcousticEncoder
from kaine.modules.context import CONTEXT_DIM
from kaine.modules.interoception.detector import AlertResult
from kaine.modules.interoception.forward import SubstrateForwardModel
from kaine.modules.interoception.module import Interoception


def _bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    return AsyncBus(BusConfig(password="x", audit_required=False), client=client)


def _workspace(source: str, salience: float, score: float) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(
        tick_index=1,
        selected_events=[
            (
                "1-0",
                Event(
                    source=source,
                    type=f"{source}.report",
                    payload={"k": 1},
                    salience=salience,
                    timestamp=datetime.now(timezone.utc),
                ),
            )
        ],
        inhibited=False,
        salience_scores={"1-0": score},
        metadata={"access_threshold": 0.35},
    )


def _payloads(events):
    out = []
    for ev in events:
        if isinstance(ev, tuple):
            ev = ev[-1]
        if hasattr(ev, "payload"):
            out.append(ev.payload)
        elif isinstance(ev, dict) and "payload" in ev:
            out.append(ev["payload"])
        else:
            out.append(ev)
    return out


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


class _FixedClock:
    """Entity clock frozen in time for deterministic report timestamps."""

    def now(self) -> float:
        return 100.0


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


@pytest.mark.asyncio
async def test_interoception_report_carries_entity_time_and_awake() -> None:
    bus = _bus()
    try:
        clock = _FixedClock()
        interoception = Interoception(
            bus,
            reader=FakeMetricsReader({"cpu_percent": 10.0, "ram_percent": 20.0}),
            detector=NeverAlertDetector(),
            entity_clock=clock,
        )
        interoception._forward_model = SubstrateForwardModel(
            feature_dim=8,
            units=16,
            seed=5,
            context_dim=CONTEXT_DIM,
        )
        await interoception.on_workspace(_workspace("vision", 0.7, 0.5))
        await interoception.tick_once()

        events = await bus.read("interoception.out", last_id="0")
        reports = _typed_payloads(events, "interoception.report")
        assert reports
        assert reports[0]["entity_time_s"] == clock.now()
        assert reports[0]["awake"] is True
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_audition_perception_carries_entity_time_and_awake() -> None:
    bus = _bus()
    try:
        clock = _FixedClock()
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
        await audition.on_workspace(_workspace("interoception", 0.6, 0.6))
        await audition.process_audio(_tone(440), sample_rate=16000)

        events = await bus.read("audition.out", last_id="0")
        reports = _typed_payloads(events, "audition.perception")
        assert reports
        assert reports[0]["entity_time_s"] == clock.now()
        assert reports[0]["awake"] is True
        await audition.shutdown()
    finally:
        await bus.close()
