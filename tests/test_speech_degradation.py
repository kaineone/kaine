# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for speech backend boot wiring and degradation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import kaine.backend_state
from kaine.boot import ConfigurationError, make_vox
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.audition import Audition, FakeEmotionClassifier
from kaine.modules.vox import FakePlayer, Vox


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


@pytest.fixture(autouse=True)
def _clear_backend_failures():
    kaine.backend_state.clear_backend_failures()
    yield
    kaine.backend_state.clear_backend_failures()


class _FailingSTTClient:
    base_url = "http://test-stt"

    async def transcribe(self, audio: Any, sample_rate: int | None = None, **kwargs: Any) -> str:
        return ""

    async def aclose(self) -> None:
        return None

    async def warm_up(self) -> None:
        raise RuntimeError("native boom")


class _FailingTTSClient:
    base_url = "http://test-tts"
    synthesized: bool = False

    async def synthesize(self, text: str, **kwargs: Any) -> bytes:
        self.synthesized = True
        return b"fake-audio"

    async def aclose(self) -> None:
        return None

    async def warm_up(self) -> None:
        raise RuntimeError("native boom")


def _failure_matches(record: Any, *, module: str, backend: str, reason_sub: str) -> bool:
    rec_module = getattr(record, "module", None)
    rec_backend = getattr(record, "backend", None)
    rec_reason = getattr(record, "reason", None) or ""

    if rec_module is None and isinstance(record, dict):
        rec_module = record.get("module")
    if rec_backend is None and isinstance(record, dict):
        rec_backend = record.get("backend")
    if not rec_reason and isinstance(record, dict):
        rec_reason = record.get("reason") or ""

    return (
        rec_module == module
        and rec_backend == backend
        and reason_sub in rec_reason
    )


@pytest.mark.asyncio
async def test_audition_initialize_degrades_on_warm_up_failure(bus: AsyncBus) -> None:
    stt_client = _FailingSTTClient()
    audition = Audition(
        bus,
        stt_client=stt_client,
        emotion_classifier=FakeEmotionClassifier(),
        stt_model="moonshine-base-en",
        backend="sherpa_onnx",
        transcription_enabled=True,
    )

    await audition.initialize()

    assert audition._transcription_enabled is False
    assert any(
        _failure_matches(f, module="audition", backend="sherpa_onnx", reason_sub="native boom")
        for f in kaine.backend_state.backend_failures()
    )

    await audition.shutdown()


@pytest.mark.asyncio
async def test_vox_initialize_degrades_on_warm_up_failure(bus: AsyncBus, tmp_path: Path) -> None:
    tts_client = _FailingTTSClient()
    vox = Vox(
        bus,
        tts_client=tts_client,
        player=FakePlayer(),
        backend="sherpa_onnx",
        applied_prosody=("speed_factor",),
        voice_label="kokoro-en speaker 0",
        sink_path=tmp_path / "vox",
    )

    await vox.initialize()

    assert vox._tts_unavailable is not None
    assert "native boom" in vox._tts_unavailable
    assert any(
        _failure_matches(f, module="vox", backend="sherpa_onnx", reason_sub="native boom")
        for f in kaine.backend_state.backend_failures()
    )

    # A muted Vox does not raise: it returns empty audio (the failure event is
    # rate-limited and published at baseline salience; see the test below).
    result = await vox.synthesize_text("hello")
    assert result.bytes_produced == 0
    assert not tts_client.synthesized

    await vox.shutdown()


def test_make_vox_unknown_backend_reports_raw_value(bus: AsyncBus) -> None:
    with pytest.raises(ConfigurationError, match=r"'not_a_backend'"):
        make_vox(bus, {"backend": "not_a_backend"})


class _FakeClock:
    def __init__(self, now: float = 0.0) -> None:
        self._now = now

    def now(self) -> float:
        return self._now

    def advance(self, delta: float) -> None:
        self._now += delta


@pytest.mark.asyncio
async def test_dormant_muted_vox_publishes_nothing(bus: AsyncBus, tmp_path: Path) -> None:
    tts_client = _FailingTTSClient()
    vox = Vox(
        bus,
        tts_client=tts_client,
        player=FakePlayer(),
        backend="sherpa_onnx",
        applied_prosody=("speed_factor",),
        sink_path=tmp_path / "vox",
    )
    await vox.initialize()
    assert vox._tts_unavailable is not None

    vox.set_dormant(True)
    assert vox.dormant is True

    published = []

    async def _capture(*args, **kwargs):
        published.append((args, kwargs))

    vox._publish_event = _capture

    result = await vox.synthesize_text("hello")
    assert result.audio == b""
    assert published == []

    await vox.shutdown()


@pytest.mark.asyncio
async def test_muted_vox_publishes_baseline_failure_once_per_60s(bus: AsyncBus, tmp_path: Path) -> None:
    clock = _FakeClock()
    tts_client = _FailingTTSClient()
    vox = Vox(
        bus,
        tts_client=tts_client,
        player=FakePlayer(),
        backend="sherpa_onnx",
        applied_prosody=("speed_factor",),
        baseline_salience=0.25,
        alert_salience=0.75,
        sink_path=tmp_path / "vox",
        entity_clock=clock,
    )
    await vox.initialize()
    assert vox._tts_unavailable is not None
    assert not vox.dormant

    published = []

    async def _capture(text, params, result, *, success, error=None, salience=None):
        published.append(
            {
                "text": text,
                "params": params,
                "result": result,
                "success": success,
                "error": error,
                "salience": salience,
            }
        )

    vox._publish_event = _capture

    first = await vox.synthesize_text("first")
    assert first.audio == b""
    assert len(published) == 1
    assert published[0]["success"] is False
    assert "text-to-speech unavailable" in (published[0]["error"] or "")
    assert published[0]["salience"] == 0.25

    clock.advance(10.0)
    second = await vox.synthesize_text("second")
    assert second.audio == b""
    assert len(published) == 1

    clock.advance(60.0)
    third = await vox.synthesize_text("third")
    assert third.audio == b""
    assert len(published) == 2
    assert published[1]["success"] is False
    assert published[1]["salience"] == 0.25

    await vox.shutdown()
