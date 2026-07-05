# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Self-hearing suppression: the SpeakingGate, audition dropping its own
voice during playback, vox opening the window, and boot wiring."""
import io
import wave

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.audition.module import Audition
from kaine.modules.audition.stt_client import FakeSTTClient
from kaine.modules.audition.emotion import FakeEmotionClassifier
from kaine.modules.vox import Vox, FakePlayer, FakeTTSClient, SpeakingGate


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _wav_bytes(seconds: float, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


# ---- SpeakingGate -----------------------------------------------------------

def test_gate_opens_and_closes_on_clock():
    now = [100.0]
    gate = SpeakingGate(clock=lambda: now[0])
    assert gate.is_speaking() is False
    gate.mark_speaking(5.0)
    assert gate.is_speaking() is True
    now[0] += 4.9
    assert gate.is_speaking() is True
    now[0] += 0.2  # past the 5.0s window
    assert gate.is_speaking() is False


def test_gate_mark_extends_never_shrinks():
    now = [0.0]
    gate = SpeakingGate(clock=lambda: now[0])
    gate.mark_speaking(10.0)
    gate.mark_speaking(1.0)  # shorter; must not pull the deadline in
    now[0] = 5.0
    assert gate.is_speaking() is True


def test_gate_nonpositive_duration_is_noop():
    gate = SpeakingGate()
    gate.mark_speaking(0.0)
    gate.mark_speaking(-3.0)
    assert gate.is_speaking() is False


# ---- audition drops self-heard capture --------------------------------------

def _make_audition(bus, **overrides):
    return Audition(
        bus,
        stt_client=FakeSTTClient(responses=["hello world"]),
        emotion_classifier=FakeEmotionClassifier(),
        stt_model="fake-stt",
        **overrides,
    )


@pytest.mark.asyncio
async def test_audition_drops_capture_while_speaking(bus: AsyncBus):
    gate = SpeakingGate()
    gate.mark_speaking(60.0)  # window wide open
    audition = _make_audition(bus, speaking_gate=gate)
    await audition.initialize()
    try:
        stt, emo = await audition.process_audio(b"\x00" * 1024, sample_rate=16000)
        assert (stt, emo) == (None, None)
        # Nothing transcribed, nothing published.
        assert audition.stt_client.transcriptions == []
        entries = await bus.read("audition.out", last_id="0", count=10)
        assert entries == []
    finally:
        await audition.shutdown()


@pytest.mark.asyncio
async def test_audition_processes_when_not_speaking(bus: AsyncBus):
    gate = SpeakingGate()  # never marked → closed
    audition = _make_audition(bus, speaking_gate=gate)
    await audition.initialize()
    try:
        await audition.process_audio(b"\x00" * 1024, sample_rate=16000)
        entries = await bus.read("audition.out", last_id="0", count=10)
        types = sorted(e.type for _, e in entries)
        assert types == ["audition.emotion", "audition.transcription"]
    finally:
        await audition.shutdown()


# ---- vox opens the window (only when suppression is on) ---------------

def _make_vox(bus, tmp_path, **overrides):
    overrides.setdefault("player", FakePlayer())
    return Vox(
        bus,
        tts_client=FakeTTSClient(canned_audio=_wav_bytes(0.5)),
        sink_path=tmp_path / "vox",
        predefined_voice_id="v.wav",
        **overrides,
    )


@pytest.mark.asyncio
async def test_vox_opens_window_when_suppressing(bus, tmp_path):
    gate = SpeakingGate()
    vox = _make_vox(
        bus, tmp_path, suppress_self_hearing=True, speaking_gate=gate
    )
    await vox.initialize()
    try:
        assert gate.is_speaking() is False
        await vox.synthesize_text("hi")
        # 0.5s clip + 600ms hangover → window is open right after.
        assert gate.is_speaking() is True
    finally:
        await vox.shutdown()


@pytest.mark.asyncio
async def test_vox_stays_full_duplex_when_not_suppressing(bus, tmp_path):
    gate = SpeakingGate()
    vox = _make_vox(
        bus, tmp_path, suppress_self_hearing=False, speaking_gate=gate
    )
    await vox.initialize()
    try:
        await vox.synthesize_text("hi")
        assert gate.is_speaking() is False  # window never opened
    finally:
        await vox.shutdown()


# ---- boot wires one shared gate into both modules ---------------------------

@pytest.mark.asyncio
async def test_build_registry_shares_one_gate(bus: AsyncBus):
    from kaine.boot import build_registry

    config = {
        "modules": {"audition": True, "vox": True},
        "audition": {},
        "vox": {"playback_enabled": False},
    }
    registry = build_registry(bus, config)
    audition = registry.get("audition")
    vox = registry.get("vox")
    assert audition._speaking_gate is not None
    assert audition._speaking_gate is vox._speaking_gate
