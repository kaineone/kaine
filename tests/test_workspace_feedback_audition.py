# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for workspace feedback in the audition module."""

from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np
import pytest

from kaine.boot.factories.audition import make_audition
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.audition import Audition, FakeEmotionClassifier, FakeSTTClient
from kaine.modules.audition.acoustic import FakeAcousticEncoder
from kaine.modules.feedback import TopDownBlend
from kaine.modules.intensity import graded_intensity
from kaine.workspace.feedback import FEEDBACK_KEY, WorkspaceFeedbackSettings


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


def _event_objects(events, event_type):
    """Return Event objects of a specific type."""
    out = []
    for ev in events:
        if isinstance(ev, tuple):
            ev = ev[-1]
        if getattr(ev, "type", None) == event_type:
            out.append(ev)
    return out


def _tone(freq: float, seconds: float = 0.2, amp: float = 0.3, sr: int = 16000) -> bytes:
    samples = np.arange(int(sr * seconds))
    wave = (amp * np.sin(2.0 * math.pi * freq * samples / sr) * 32767).astype(np.int16)
    return wave.tobytes()


def _common_audition_kwargs():
    """Constructor arguments that avoid external backends in tests."""
    return {
        "stt_client": FakeSTTClient(responses=["x"]),
        "emotion_classifier": FakeEmotionClassifier(),
        "stt_model": "fake-stt",
        "general_audition": True,
        "acoustic_encoder": FakeAcousticEncoder(embedding_dim=8),
    }


@pytest.mark.asyncio
async def test_feedback_off_is_bit_for_bit() -> None:
    """With the feedback arm off the acoustic report is unchanged."""
    torch = pytest.importorskip("torch")
    common = _common_audition_kwargs()

    clock_a = _MutableClock(0.0)
    bus_a = _bus()
    torch.manual_seed(0)
    mod_a = Audition(
        bus_a, entity_clock=clock_a, workspace_feedback=None, **common
    )
    await mod_a.initialize()

    clock_b = _MutableClock(0.0)
    bus_b = _bus()
    torch.manual_seed(0)
    mod_b = Audition(bus_b, entity_clock=clock_b, **common)
    await mod_b.initialize()

    clock_a.t = clock_b.t = 10.0
    await mod_a.on_workspace(_workspace(1, False, 0.5, published_at=10.0))
    await mod_b.on_workspace(_workspace(1, False, 0.5, published_at=10.0))

    for i, freq in enumerate([440, 490, 540, 600], start=1):
        clock_a.t = clock_b.t = 10.0 + i
        await mod_a.process_audio(_tone(freq), sample_rate=16000)
        await mod_b.process_audio(_tone(freq), sample_rate=16000)

    payloads_a = _typed_payloads(
        await bus_a.read("audition.out", last_id="0"), "audition.perception"
    )
    payloads_b = _typed_payloads(
        await bus_b.read("audition.out", last_id="0"), "audition.perception"
    )
    assert payloads_a
    assert len(payloads_a) == len(payloads_b)
    for a, b in zip(payloads_a, payloads_b):
        assert "workspace_feedback" not in a
        assert "workspace_feedback" not in b
        for drop in ("entity_time_s", "context_age_s", "prediction_context_age_s"):
            a = {k: v for k, v in a.items() if k != drop}
            b = {k: v for k, v in b.items() if k != drop}
        assert a == b

    await mod_a.shutdown()
    await mod_b.shutdown()


@pytest.mark.asyncio
async def test_feedback_on_wraps_and_adopts_broadcast() -> None:
    """Feedback on wraps the acoustic forward model and adopts broadcast state."""
    torch = pytest.importorskip("torch")
    torch.manual_seed(0)
    bus = _bus()
    clock = _MutableClock(0.0)
    settings = WorkspaceFeedbackSettings(arm="full")
    audition = Audition(
        bus,
        entity_clock=clock,
        workspace_feedback=settings,
        **_common_audition_kwargs(),
    )
    await audition.initialize()
    assert isinstance(audition._acoustic_forward_model, TopDownBlend)

    ws = _workspace(2, False, 0.5, published_at=5.0)
    ws.metadata["workspace_feedback"] = {
        "gains": {"audition": 1.2},
        "sequence_prediction": [0.05] * 24,
    }
    await audition.on_workspace(ws)
    assert audition._feedback_channel is not None
    assert audition._feedback_channel.gain == pytest.approx(1.2)
    assert audition._feedback_channel.sequence_prediction == tuple([0.05] * 24)

    ws2 = _workspace(3, True, 0.1)
    ws2.metadata["workspace_feedback"] = {
        "gains": {"audition": 0.9},
        "sequence_prediction": [0.1] * 24,
    }
    await audition.on_workspace(ws2)
    assert audition._feedback_channel.gain == pytest.approx(1.2)
    assert audition._feedback_channel.sequence_prediction == tuple([0.05] * 24)

    for i, freq in enumerate([440, 490, 540], start=1):
        clock.t = 5.0 + i
        await audition.process_audio(_tone(freq), sample_rate=16000)

    reports = _typed_payloads(
        await bus.read("audition.out", last_id="0"), "audition.perception"
    )
    assert len(reports) == 3
    for report in reports:
        assert FEEDBACK_KEY in report
        fb = report[FEEDBACK_KEY]
        assert set(fb) == {
            "disagreement",
            "error_ratio",
            "gain",
            "top_down_weight",
            "own_error",
            "top_down_error",
        }
        assert fb["gain"] == pytest.approx(1.2)

    await audition.shutdown()


@pytest.mark.asyncio
async def test_feedback_gain_applied_to_intensity() -> None:
    """The adopted gain scales graded intensity only when the arm requests it."""
    torch = pytest.importorskip("torch")

    async def run_one(arm: str, injected_gain: float) -> int:
        torch.manual_seed(0)
        bus = _bus()
        clock = _MutableClock(0.0)
        settings = WorkspaceFeedbackSettings(arm=arm)
        audition = Audition(
            bus,
            entity_clock=clock,
            workspace_feedback=settings,
            **_common_audition_kwargs(),
        )
        await audition.initialize()

        ws = _workspace(1, False, 0.5, published_at=1.0)
        ws.metadata["workspace_feedback"] = {
            "gains": {"audition": injected_gain},
            "sequence_prediction": [0.05] * 24,
        }
        await audition.on_workspace(ws)

        freqs = [350, 370, 400, 430, 470, 520, 580, 650, 720, 800]
        for i, freq in enumerate(freqs, start=1):
            clock.t = 1.0 + i * 0.5
            await audition.process_audio(_tone(freq, seconds=0.15), sample_rate=16000)

        checked = 0
        for ev in _event_objects(
            await bus.read("audition.out", last_id="0"), "audition.perception"
        ):
            payload = ev.payload
            if payload["alert"]:
                continue
            fb = payload[FEEDBACK_KEY]
            if arm == "full":
                ratio = injected_gain * payload["normalised_error"]
                assert fb["gain"] == pytest.approx(injected_gain)
            else:
                ratio = payload["normalised_error"]
                assert fb["gain"] == pytest.approx(1.0)
            expected = graded_intensity(
                audition._baseline_salience, audition._alert_salience, ratio
            )
            assert ev.salience == pytest.approx(expected, rel=1e-5)
            checked += 1

        await audition.shutdown()
        return checked

    assert (await run_one("full", 1.2)) >= 1
    assert (await run_one("head_only", 1.2)) >= 1


@pytest.mark.asyncio
async def test_feedback_leaves_tone_path_untouched() -> None:
    """The tone/speech forward model is not wrapped by workspace feedback."""
    torch = pytest.importorskip("torch")
    torch.manual_seed(0)
    audition = Audition(
        _bus(),
        entity_clock=_MutableClock(0.0),
        workspace_feedback=WorkspaceFeedbackSettings(arm="full"),
        **_common_audition_kwargs(),
    )
    assert isinstance(audition._acoustic_forward_model, TopDownBlend)
    assert not isinstance(audition._forward_model, TopDownBlend)
    await audition.shutdown()


def test_factory_feedback_section() -> None:
    """The reserved workspace_feedback section is parsed and passed through."""
    bus = _bus()
    section_on = {
        "capture_enabled": True,
        "general_audition": True,
        "workspace_feedback": {"enabled": True, "arm": "full"},
    }
    audition_on = make_audition(bus, section_on)
    assert audition_on._feedback_settings is not None
    assert audition_on._feedback_settings.arm == "full"

    section_off = {
        "capture_enabled": True,
        "general_audition": True,
        "workspace_feedback": {"enabled": True, "arm": "off"},
    }
    audition_off = make_audition(bus, section_off)
    assert audition_off._feedback_settings is None
