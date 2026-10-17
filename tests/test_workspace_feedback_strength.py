# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Stronger regression tests for workspace feedback blending, gain
competition, and gain application. These tests are designed to fail under
the specific mutations named in each test while passing on the current
code.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np
import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.context import CONTEXT_DIM
from kaine.modules.feedback import TopDownBlend, blend_weights
from kaine.modules.intensity import graded_intensity
from kaine.modules.interoception.detector import AlertResult
from kaine.modules.interoception.forward import SubstrateForwardModel
from kaine.modules.interoception.module import Interoception
from kaine.modules.vision import Vision
from kaine.modules.vision.forward import LatentForwardModel
from kaine.workspace.feedback import (
    FEEDBACK_KEY,
    PROCESSORS,
    REPORT_TYPES,
    SEQUENCE_PREDICTION_DIM,
    FeedbackController,
    WorkspaceFeedbackSettings,
)


def _l2(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _mean(seq):
    return sum(seq) / len(seq) if seq else 0.0


class FakeForwardModel:
    """Minimal forward model implementing the processor contract."""

    def __init__(self):
        self._last_prediction = None
        self._last_null_prediction = None
        self._last_input_context = None
        self.last_null_error = None
        self.last_scored_had_context = False
        self.last_error_defined = False
        self.last_reading_skipped = True
        self._after_skip = True
        self.suspended = False
        self.context_dim = CONTEXT_DIM
        self.marker = "inner"
        self._buffer = []

    def _predict_next(self, latent):
        return [0.5 * v for v in latent]

    def _predict_null(self, latent):
        return [0.25 * v for v in latent]

    def _adapt_toward(self, latent, context):
        pass

    def step(self, latent, context=None, null_context=None):
        if any(not math.isfinite(v) for v in latent):
            self.last_null_error = None
            self.last_scored_had_context = False
            self._last_prediction = None
            self._last_null_prediction = None
            self._last_input_context = None
            self.last_error_defined = False
            self._after_skip = True
            self.last_reading_skipped = True
            return 0.0

        self.last_reading_skipped = False
        self.last_error_defined = not self._after_skip
        self._after_skip = False

        if self._last_prediction is None:
            prediction_error = 0.0
            self.last_scored_had_context = False
            self.last_null_error = None
        else:
            diffs = [(a - b) ** 2 for a, b in zip(latent, self._last_prediction)]
            prediction_error = math.sqrt(sum(diffs))
            self.last_scored_had_context = self._last_input_context is not None
            if self._last_null_prediction is not None:
                null_diffs = [
                    (a - b) ** 2 for a, b in zip(latent, self._last_null_prediction)
                ]
                self.last_null_error = math.sqrt(sum(null_diffs))
            else:
                self.last_null_error = None

        if not self.suspended and self._last_prediction is not None:
            self._adapt_toward(latent, self._last_input_context)

        self._buffer.append(list(latent))
        self._last_prediction = self._predict_next(latent)
        self._last_input_context = context

        if null_context is not None and self.context_dim > 0:
            self._last_null_prediction = self._predict_null(latent)
        else:
            self._last_null_prediction = None

        return prediction_error


def _report(source, *, ratio=None, disagreement=None, gain=1.0, eid=None, salience=0.6):
    payload = {
        FEEDBACK_KEY: {
            "error_ratio": ratio,
            "disagreement": disagreement,
            "gain": gain,
        }
    }
    return (
        eid or f"{source}:1",
        Event(
            source=source,
            type=REPORT_TYPES[source],
            payload=payload,
            salience=salience,
            timestamp=datetime.now(timezone.utc),
        ),
    )


def _snapshot(events, *, scores=None, threshold=0.35, inhibited=False):
    scores = dict(scores) if scores else {}
    for eid, _ in events:
        scores.setdefault(eid, 0.6)
    return WorkspaceSnapshot(
        tick_index=0,
        selected_events=events,
        inhibited=inhibited,
        salience_scores=scores,
        metadata={"access_threshold": threshold},
    )


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


class _FixedClock:
    """Entity-clock stand-in that never advances."""

    def now(self) -> float:
        return 100.0

    def wall(self) -> float:
        return 100.0


class FakeCounterSmall:
    model_id = "fake/counter"
    latent_dim = 4
    clip_len = 1

    def __init__(self):
        self._n = 0

    async def load(self):
        return None

    async def shutdown(self):
        return None

    async def encode(self, image):  # noqa: ARG002
        self._n += 1
        # Small drift plus an alternating term to keep errors bounded
        # but non-zero.
        return [
            0.1 + self._n * 0.005 + 0.02 * math.sin(self._n),
            0.2 - self._n * 0.003,
            0.3 + 0.01 * math.cos(self._n),
            0.4,
        ]

    async def encode_clip(self, frames):
        return await self.encode(frames[-1])


async def _vision(bus, *, feedback=None, encoder=None):
    vision = Vision(
        bus,
        encoder=encoder or FakeCounterSmall(),
        forward_prediction=True,
        workspace_feedback=feedback,
        entity_clock=_FixedClock(),
    )
    await vision.initialize()
    vision._forward_model = LatentForwardModel(
        latent_dim=4,
        units=8,
        context_dim=CONTEXT_DIM,
        seed=4,
    )
    return vision


def _feedback_snapshot(tick, *, gain=1.2, inhibited=False, seq=None):
    if seq is None:
        seq = [0.05] * SEQUENCE_PREDICTION_DIM
    return WorkspaceSnapshot(
        tick_index=tick,
        selected_events=[
            (
                "1-0",
                Event(
                    source="interoception",
                    type="interoception.report",
                    payload={"k": 1},
                    salience=0.6,
                    timestamp=datetime.now(timezone.utc),
                ),
            )
        ],
        inhibited=inhibited,
        salience_scores={"1-0": 0.5},
        metadata={
            "access_threshold": 0.35,
            "workspace_feedback": {
                "gains": {"vision": gain},
                "sequence_prediction": seq,
            },
        },
    )


class _MutableClock:
    """Callable entity-clock for deterministic ageing."""

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
    return [e[-1] if isinstance(e, tuple) else e for e in entries]


def _typed_payloads(events, event_type):
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


def test_blend_weights_inverse_square():
    """blend_weights must use the inverse SQUARE of the mean errors.

    Mutation: replace 1 / own_mean**2 with 1 / own_mean.
    """
    w_own, w_top = blend_weights(2.0, 1.0)
    assert w_own == pytest.approx(0.2, rel=1e-12)
    assert w_top == pytest.approx(0.8, rel=1e-12)

    w_own, w_top = blend_weights(1.0, 3.0)
    assert w_own == pytest.approx(0.9, rel=1e-12)
    assert w_top == pytest.approx(0.1, rel=1e-12)


def test_null_blend_includes_top_down_head():
    """The null-context blend includes the top-down head prediction.

    Mutation: the null blend is the own null prediction only.
    """
    fake = FakeForwardModel()
    blend = TopDownBlend(fake, window=32, lr=0.05)

    context = [0.3] * CONTEXT_DIM
    null_context = [0.0] * CONTEXT_DIM
    seq = [0.2] * SEQUENCE_PREDICTION_DIM

    features = [
        [0.1] * 8,
        [0.25] * 8,
        [0.4] * 8,
        [0.55] * 8,
    ]
    for f in features:
        blend.step(
            f,
            context=context,
            null_context=null_context,
            sequence_prediction=seq,
        )

    f_prev = features[-1]
    f_next = [0.7] * 8

    x0 = blend.head.regressor(null_context, seq)
    top_null = blend.head.predict(x0)
    own_null = [0.25 * v for v in f_prev]

    w_own, w_top = blend_weights(
        _mean(blend._own_errors),
        _mean(blend._top_errors),
    )
    assert w_top > 0.0
    assert any(v != 0.0 for v in top_null)

    expected_null = [w_own * o + w_top * t for o, t in zip(own_null, top_null)]
    assert blend._blend_null == pytest.approx(expected_null, rel=1e-12)

    blend.step(
        f_next,
        context=context,
        null_context=null_context,
        sequence_prediction=seq,
    )

    assert blend.last_null_error == pytest.approx(
        _l2(f_next, expected_null), rel=1e-9
    )
    assert blend.last_null_error != pytest.approx(
        _l2(f_next, own_null), rel=1e-9
    )


def test_gain_ceiling_pi_max_clip():
    """pi_max clip in _shift prevents gains from exceeding the ceiling.

    Mutation: remove the pi_max term from _shift.
    """
    settings = WorkspaceFeedbackSettings.from_section(
        {
            "enabled": True,
            "arm": "full",
            "gain_relax_s": 1e9,
            "refractory_s": 1.0,
        }
    )
    ctrl = FeedbackController(settings, clock=lambda: 0.0)

    for t in range(0, 100, 10):
        if (t // 10) % 2 == 0:
            conflicting = _report(
                "vision", ratio=2.5, disagreement=3.0, eid="vision:1"
            )
        else:
            conflicting = _report(
                "interoception", ratio=2.5, disagreement=3.0, eid="intero:1"
            )
        audition = _report("audition", ratio=0.5, eid="aud:1")
        snap = _snapshot([conflicting, audition])

        meta = ctrl.on_broadcast(snap, now=float(t))
        assert meta is not None

        for processor in PROCESSORS:
            assert settings.pi_min <= ctrl.gains[processor] <= settings.pi_max
        mean = sum(ctrl.gains.values()) / len(PROCESSORS)
        assert mean == pytest.approx(1.0, abs=1e-12)

    assert ctrl.gains["audition"] == pytest.approx(1.25, abs=1e-9)


def test_full_arm_moves_toward_lowest_precision_weighted_error():
    """The full arm moves gain from the conflicting processor to the most
    precise other accessed processor.

    Mutation: choose the highest precision-weighted error instead.
    """
    settings = WorkspaceFeedbackSettings.from_section(
        {
            "enabled": True,
            "arm": "full",
            "gain_relax_s": 1e9,
            "refractory_s": 10.0,
        }
    )
    ctrl = FeedbackController(settings, clock=lambda: 0.0)

    # Case 1: audition is the most precise other processor.
    vis = _report("vision", ratio=2.5, disagreement=3.0)
    aud = _report("audition", ratio=0.5)
    inter = _report("interoception", ratio=1.5)
    snap = _snapshot([vis, aud, inter])

    meta = ctrl.on_broadcast(snap, now=0.0)
    assert meta is not None
    assert meta["gains"] == pytest.approx(
        {"vision": 0.9, "audition": 1.1, "interoception": 1.0}
    )

    # Case 2: reported gains swap the order; interoception is most precise.
    ctrl2 = FeedbackController(settings, clock=lambda: 0.0)
    vis2 = _report("vision", ratio=2.5, disagreement=3.0)
    aud2 = _report("audition", ratio=0.5, gain=1.25)
    inter2 = _report("interoception", ratio=0.6, gain=0.8)
    snap2 = _snapshot([vis2, aud2, inter2])

    meta2 = ctrl2.on_broadcast(snap2, now=0.0)
    assert meta2 is not None
    assert meta2["gains"] == pytest.approx(
        {"vision": 0.9, "audition": 1.0, "interoception": 1.1}
    )


@pytest.mark.asyncio
async def test_vision_applies_gain_to_graded_intensity(bus):
    """Vision multiplies the adopted gain into the intensity argument.

    Mutation: the gain is dropped before graded_intensity.
    """
    full_settings = WorkspaceFeedbackSettings.from_section(
        {"enabled": True, "arm": "full"}
    )
    vision = await _vision(bus, feedback=full_settings)

    # Trigger wrapping and warm-up reports.
    await vision.process_frame(None)
    assert isinstance(vision._forward_model, TopDownBlend)

    await vision.on_workspace(_feedback_snapshot(1, gain=1.2))

    for _ in range(15):
        await vision.process_frame(None)

    entries = await bus.read("vision.out", last_id="0")
    counted = 0
    for _, event in entries:
        payload = event.payload
        if payload.get("alert"):
            continue
        fb = payload.get(FEEDBACK_KEY, {})
        if abs(fb.get("gain", 1.0) - 1.2) > 1e-9:
            continue
        ratio = payload.get("normalised_error")
        if ratio is None or not (0.0 < ratio < 1.6):
            continue

        counted += 1
        expected = graded_intensity(
            vision._baseline_salience,
            vision._alert_salience,
            1.2 * ratio,
        )
        assert event.salience == pytest.approx(expected)

        ungained = graded_intensity(
            vision._baseline_salience,
            vision._alert_salience,
            ratio,
        )
        assert abs(event.salience - ungained) > 1e-9

    assert counted >= 1, "no non-alert report with error ratio in (0, 1.6)"


@pytest.mark.asyncio
async def test_interoception_applies_gain_to_graded_intensity():
    """Interoception multiplies the adopted gain into the intensity argument.

    Mutation: the gain is dropped from graded_intensity(..., gain * error_ratio).
    """
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

        await intero.on_workspace(
            _feedback_workspace(
                2,
                False,
                0.5,
                gain=1.2,
                sequence_prediction=(0.05,) * SEQUENCE_PREDICTION_DIM,
                published_at=2.0,
            )
        )

        for t in range(2, 17):
            clock.t = float(t)
            await intero.tick_once()

        events = await bus.read("interoception.out", last_id="0")
        counted = 0
        for event in _evs(events):
            if getattr(event, "type", None) != "interoception.report":
                continue
            report = event.payload
            fb = report.get("workspace_feedback", {})
            if abs(fb.get("gain", 1.0) - 1.2) > 1e-9:
                continue
            ratio = fb.get("error_ratio")
            if ratio is None or not (0.0 < ratio < 1.6):
                continue

            counted += 1
            expected = graded_intensity(
                intero._baseline_salience,
                intero._alert_salience,
                1.2 * ratio,
            )
            assert event.salience == pytest.approx(expected)

            ungained = graded_intensity(
                intero._baseline_salience,
                intero._alert_salience,
                ratio,
            )
            assert abs(event.salience - ungained) > 1e-9

        assert counted >= 1, "no report with error ratio in (0, 1.6)"
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_vision_uses_adopted_sequence_prediction_in_head(bus):
    """After adopting a sequence prediction, the vision blend head regressor
    contains it in the sequence slot.
    """
    settings = WorkspaceFeedbackSettings.from_section({"enabled": True, "arm": "full"})
    vision = await _vision(bus, feedback=settings)

    await vision.process_frame(None)
    assert isinstance(vision._forward_model, TopDownBlend)

    seq = [0.05] * SEQUENCE_PREDICTION_DIM
    await vision.on_workspace(_feedback_snapshot(1, gain=1.0, seq=seq))
    await vision.process_frame(None)

    regressor = vision._forward_model._regressor
    assert regressor is not None
    assert len(regressor) == CONTEXT_DIM + SEQUENCE_PREDICTION_DIM + 1
    assert np.allclose(
        regressor[CONTEXT_DIM : CONTEXT_DIM + SEQUENCE_PREDICTION_DIM],
        0.05,
        atol=1e-12,
    )
