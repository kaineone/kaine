# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for workspace feedback in the interoception module."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kaine.boot.factories.interoception import make_interoception
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.context import CONTEXT_DIM
from kaine.modules.feedback import TopDownBlend
from kaine.modules.intensity import graded_intensity
from kaine.modules.interoception.detector import AlertResult
from kaine.modules.interoception.forward import SubstrateForwardModel
from kaine.modules.interoception.module import Interoception
from kaine.workspace.feedback import WorkspaceFeedbackSettings


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
    metadata: dict | None = None,
    published_at: float | None = None,
) -> WorkspaceSnapshot:
    if metadata is None:
        metadata = {"access_threshold": 0.35}
    return WorkspaceSnapshot(
        tick_index=tick_index,
        selected_events=[
            (
                "1-0",
                Event(
                    source="vision",
                    type="vision.report",
                    payload={"k": 1},
                    salience=0.7 if not inhibited else 0.1,
                    timestamp=datetime.now(timezone.utc),
                ),
            )
        ],
        inhibited=inhibited,
        salience_scores={"1-0": score},
        metadata=metadata,
        published_at=published_at,
    )


def _feedback_workspace(
    tick_index: int,
    inhibited: bool,
    score: float,
    gain: float,
    sequence_prediction: tuple[float, ...],
    published_at: float | None = None,
) -> WorkspaceSnapshot:
    metadata = {
        "access_threshold": 0.35,
        "workspace_feedback": {
            "gains": {"interoception": gain},
            "sequence_prediction": list(sequence_prediction),
        },
    }
    return _workspace(tick_index, inhibited, score, metadata=metadata, published_at=published_at)


def _evs(entries):
    """The events of bus entries, which are (entry_id, event) pairs."""
    return [e[-1] if isinstance(e, tuple) else e for e in entries]


def _typed_payloads(events, event_type):
    """Return payloads for events of a specific type."""
    out = []
    for ev in events:
        if isinstance(ev, tuple):
            ev = ev[-1]
        if getattr(ev, "type", None) == event_type and hasattr(ev, "payload"):
            out.append(ev.payload)
    return out


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


class SteppingMetricsReader(FakeMetricsReader):
    """Metrics reader whose cpu_percent changes on every read."""

    def __init__(self) -> None:
        super().__init__({"cpu_percent": 10.0, "ram_percent": 20.0})
        self._step = 0
        self._cpu_values = [10.0, 30.0, 15.0, 40.0]

    async def read_metrics(self) -> dict[str, float]:
        metrics = dict(self._metrics)
        metrics["cpu_percent"] = self._cpu_values[self._step % len(self._cpu_values)]
        self._step += 1
        return metrics


class NeverAlertDetector:
    def evaluate(self, metrics: dict[str, float]) -> AlertResult:  # noqa: ARG002
        return AlertResult()


def _make_forward_model():
    return SubstrateForwardModel(
        feature_dim=8, units=16, seed=5, context_dim=CONTEXT_DIM
    )


@pytest.mark.asyncio
async def test_feedback_off_bit_for_bit() -> None:
    """With feedback off the report path is byte-identical to the no-argument case."""
    bus_off = _bus()
    bus_none = _bus()
    try:
        clock_off = _MutableClock(0.0)
        clock_none = _MutableClock(0.0)
        intero_off = Interoception(
            bus_off,
            reader=SteppingMetricsReader(),
            detector=NeverAlertDetector(),
            entity_clock=clock_off,
            workspace_feedback=None,
        )
        intero_none = Interoception(
            bus_none,
            reader=SteppingMetricsReader(),
            detector=NeverAlertDetector(),
            entity_clock=clock_none,
        )
        intero_off._forward_model = _make_forward_model()
        intero_none._forward_model = _make_forward_model()

        # First tick with no broadcast context.
        clock_off.t = clock_none.t = 1.0
        await intero_off.tick_once()
        await intero_none.tick_once()

        # Accessed broadcasts.
        await intero_off.on_workspace(_workspace(1, False, 0.5, published_at=1.0))
        await intero_none.on_workspace(_workspace(1, False, 0.5, published_at=1.0))
        clock_off.t = clock_none.t = 2.0
        await intero_off.tick_once()
        await intero_none.tick_once()

        await intero_off.on_workspace(_workspace(2, True, 0.1, published_at=2.0))
        await intero_none.on_workspace(_workspace(2, True, 0.1, published_at=2.0))
        clock_off.t = clock_none.t = 3.0
        await intero_off.tick_once()
        await intero_none.tick_once()

        events_off = await bus_off.read("interoception.out", last_id="0")
        events_none = await bus_none.read("interoception.out", last_id="0")

        reports_off = _typed_payloads(events_off, "interoception.report")
        reports_none = _typed_payloads(events_none, "interoception.report")
        assert reports_off
        assert len(reports_off) == len(reports_none)

        skipped = {
            "entity_time_s",
            "context_age_s",
            "prediction_context_age_s",
            "metrics",
        }
        for off, none in zip(reports_off, reports_none):
            stripped_off = {k: v for k, v in off.items() if k not in skipped}
            stripped_none = {k: v for k, v in none.items() if k not in skipped}
            assert stripped_off == stripped_none
            assert "workspace_feedback" not in off
            assert "workspace_feedback" not in none

        def _sals(events):
            return [
                ev.salience
                for ev in _evs(events)
                if isinstance(ev, Event) and ev.type == "interoception.report"
            ]

        assert _sals(events_off)
        assert _sals(events_off) == _sals(events_none)
    finally:
        await bus_off.close()
        await bus_none.close()


@pytest.mark.asyncio
async def test_feedback_on_wraps_and_payload_keys() -> None:
    """Feedback on wraps the forward model and adds the feedback payload."""
    bus = _bus()
    try:
        settings = WorkspaceFeedbackSettings(arm="full", head_learning_rate=1e-3)
        clock = _MutableClock(0.0)
        intero = Interoception(
            bus,
            reader=SteppingMetricsReader(),
            detector=NeverAlertDetector(),
            entity_clock=clock,
            workspace_feedback=settings,
        )
        intero._forward_model = _make_forward_model()

        clock.t = 1.0
        await intero.tick_once()
        assert isinstance(intero._forward_model, TopDownBlend)

        events = await bus.read("interoception.out", last_id="0")
        reports = _typed_payloads(events, "interoception.report")
        assert len(reports) == 1
        fb = reports[0]["workspace_feedback"]
        assert set(fb) == {
            "disagreement",
            "error_ratio",
            "gain",
            "top_down_weight",
            "own_error",
            "top_down_error",
        }

        await intero.on_workspace(
            _feedback_workspace(
                2,
                False,
                0.5,
                gain=1.2,
                sequence_prediction=(0.05,) * 24,
                published_at=2.0,
            )
        )
        assert intero._feedback_channel is not None
        assert intero._feedback_channel.gain == 1.2
        assert intero._feedback_channel.sequence_prediction == (0.05,) * 24

        # An inhibited broadcast must not overwrite the adopted gain.
        await intero.on_workspace(
            _feedback_workspace(
                3,
                True,
                0.1,
                gain=0.9,
                sequence_prediction=(0.1,) * 24,
                published_at=3.0,
            )
        )
        assert intero._feedback_channel.gain == 1.2
        assert intero._feedback_channel.sequence_prediction == (0.05,) * 24
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_feedback_gain_affects_intensity() -> None:
    """A full arm multiplies the error ratio; head_only keeps it unchanged."""
    bus = _bus()
    try:
        clock = _MutableClock(0.0)
        settings_full = WorkspaceFeedbackSettings(arm="full")
        intero = Interoception(
            bus,
            reader=SteppingMetricsReader(),
            detector=NeverAlertDetector(),
            entity_clock=clock,
            workspace_feedback=settings_full,
        )
        intero._forward_model = _make_forward_model()

        # Warm-up tick with no feedback broadcast.
        clock.t = 1.0
        await intero.tick_once()

        # Adopt gain and sequence prediction for the next tick.
        await intero.on_workspace(
            _feedback_workspace(
                2,
                False,
                0.5,
                gain=1.2,
                sequence_prediction=(0.05,) * 24,
                published_at=2.0,
            )
        )
        clock.t = 2.0
        await intero.tick_once()

        events = await bus.read("interoception.out", last_id="0")
        reports = _typed_payloads(events, "interoception.report")
        full_report = reports[-1]
        full_event = next(
            ev
            for ev in _evs(events)
            if isinstance(ev, Event)
            and ev.type == "interoception.report"
            and ev.payload is full_report
        )
        fb_full = full_report["workspace_feedback"]
        assert fb_full["error_ratio"] is not None
        assert fb_full["gain"] == 1.2
        expected_full = graded_intensity(
            intero._baseline_salience,
            intero._alert_salience,
            1.2 * fb_full["error_ratio"],
        )
        assert full_event.salience == pytest.approx(expected_full)

        # Repeat with arm "head_only" to verify the gain is not applied.
        bus_head = _bus()
        clock_head = _MutableClock(0.0)
        settings_head = WorkspaceFeedbackSettings(arm="head_only")
        intero_head = Interoception(
            bus_head,
            reader=SteppingMetricsReader(),
            detector=NeverAlertDetector(),
            entity_clock=clock_head,
            workspace_feedback=settings_head,
        )
        intero_head._forward_model = _make_forward_model()
        clock_head.t = 1.0
        await intero_head.tick_once()
        await intero_head.on_workspace(
            _feedback_workspace(
                2,
                False,
                0.5,
                gain=1.2,
                sequence_prediction=(0.05,) * 24,
                published_at=2.0,
            )
        )
        clock_head.t = 2.0
        await intero_head.tick_once()

        events_head = await bus_head.read("interoception.out", last_id="0")
        reports_head = _typed_payloads(events_head, "interoception.report")
        head_report = reports_head[-1]
        head_event = next(
            ev
            for ev in _evs(events_head)
            if isinstance(ev, Event)
            and ev.type == "interoception.report"
            and ev.payload is head_report
        )
        fb_head = head_report["workspace_feedback"]
        assert fb_head["error_ratio"] is not None
        assert fb_head["gain"] == 1.0
        expected_head = graded_intensity(
            intero_head._baseline_salience,
            intero_head._alert_salience,
            fb_head["error_ratio"],
        )
        assert head_event.salience == pytest.approx(expected_head)
        await bus_head.close()
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_feedback_residuals_are_blend_residuals() -> None:
    """The wrapped forward model exposes per-channel residuals after scored ticks."""
    bus = _bus()
    try:
        clock = _MutableClock(0.0)
        settings = WorkspaceFeedbackSettings(arm="full")
        intero = Interoception(
            bus,
            reader=SteppingMetricsReader(),
            detector=NeverAlertDetector(),
            entity_clock=clock,
            workspace_feedback=settings,
        )
        intero._forward_model = _make_forward_model()

        clock.t = 1.0
        await intero.tick_once()
        await intero.on_workspace(
            _workspace(1, False, 0.5, published_at=1.0)
        )
        clock.t = 2.0
        await intero.tick_once()
        await intero.on_workspace(
            _workspace(2, False, 0.6, published_at=2.0)
        )
        clock.t = 3.0
        await intero.tick_once()

        assert isinstance(intero._forward_model, TopDownBlend)
        residuals = intero._forward_model.last_residuals
        assert residuals is not None
        assert len(residuals) == 8
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_feedback_deserialize_keeps_wrap() -> None:
    """Deserialising state re-wraps the forward model when feedback is enabled."""
    bus = _bus()
    try:
        clock = _MutableClock(0.0)
        settings = WorkspaceFeedbackSettings(arm="full")
        intero = Interoception(
            bus,
            reader=SteppingMetricsReader(),
            detector=NeverAlertDetector(),
            entity_clock=clock,
            workspace_feedback=settings,
        )
        intero._forward_model = _make_forward_model()

        clock.t = 1.0
        await intero.tick_once()
        assert isinstance(intero._forward_model, TopDownBlend)

        state = intero.serialize()
        intero.deserialize(state)
        assert isinstance(intero._forward_model, TopDownBlend)
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_factory_feedback_section() -> None:
    """The factory parses the reserved workspace_feedback section."""
    bus = _bus()
    try:
        section_full = {
            "read_interval_s": 1.0,
            "workspace_feedback": {"enabled": True, "arm": "full"},
        }
        mod_full = make_interoception(bus, dict(section_full))
        assert mod_full._feedback_settings is not None
        assert mod_full._feedback_settings.arm == "full"

        section_off = {
            "read_interval_s": 1.0,
            "workspace_feedback": {"enabled": True, "arm": "off"},
        }
        mod_off = make_interoception(bus, dict(section_off))
        assert mod_off._feedback_settings is None
    finally:
        await bus.close()
