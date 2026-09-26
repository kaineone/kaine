# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the study-confounds change: audio channel labels, channel-aware
Empatheia/Volition attribution, and Vox dormancy in the womb."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.empatheia.agent import EMOTION_CATEGORIES
from kaine.modules.empatheia.module import Empatheia
from kaine.modules.empatheia.store import InMemoryAgentStore
from kaine.modules.vox import FakePlayer, FakeTTSClient, Vox
from kaine.workspace.drive_policy import DriveBiasedActionSelectionPolicy
from kaine.workspace.volition import (
    SPEAK,
    DefaultActionSelectionPolicy,
)
from tests._fakes import FakeClock

_MISSING = object()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _emotion_event(
    source_label: Any = _MISSING,
    category: str = "happy",
    confidence: float = 0.8,
    prediction_error: float = 0.0,
) -> Event:
    payload: dict[str, Any] = {
        "category": category,
        "confidence": confidence,
        "scores": {c: (1.0 if c == category else 0.0) for c in EMOTION_CATEGORIES},
        "model": "emotion2vec/emotion2vec_plus_base",
        "latency_ms": 50.0,
        "prediction_error": prediction_error,
    }
    if source_label is not _MISSING:
        payload["source_label"] = source_label
    return Event(
        source="audition",
        type="audition.emotion",
        payload=payload,
        salience=0.4,
        timestamp=datetime.now(timezone.utc),
    )


def _transcription_event(
    source_label: Any = _MISSING,
    text: str = "hello world",
) -> Event:
    payload: dict[str, Any] = {
        "text": text,
        "model": "whisper",
        "sample_rate": 16000,
        "audio_bytes_length": 1024,
        "latency_ms": 100.0,
        "prediction_error": 0.0,
    }
    if source_label is not _MISSING:
        payload["source_label"] = source_label
    return Event(
        source="audition",
        type="audition.transcription",
        payload=payload,
        salience=0.4,
        timestamp=datetime.now(timezone.utc),
    )


def _snapshot(*selected_events: tuple[str, Event]) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(
        tick_index=0,
        selected_events=list(selected_events),
        inhibited=False,
        is_experiential=True,
    )


def _vox_and_player(bus: AsyncBus, tmp_path: Path, **overrides) -> tuple[Vox, FakePlayer]:
    player = FakePlayer()
    vox = Vox(
        bus,
        tts_client=FakeTTSClient(canned_audio=b"WAV-FAKE-DATA-1234"),
        player=player,
        sink_path=tmp_path / "vox",
        predefined_voice_id="default_sample.wav",
        **overrides,
    )
    return vox, player


# ---------------------------------------------------------------------------
# 1.1 Audio source labels
# ---------------------------------------------------------------------------


def test_live_mic_source_label_helper():
    from kaine.boot import _live_mic_source_label

    for feed in ("playlist", "seeded", "womb", "screen"):
        assert _live_mic_source_label(feed) == feed
    for real in ("live", "off"):
        assert _live_mic_source_label(real) == "live_mic"
    # Unknown modes fall back to the real-microphone label.
    assert _live_mic_source_label("something_else") == "live_mic"


@pytest.mark.asyncio
async def test_make_audition_sets_source_label_per_feed(bus, monkeypatch):
    from kaine.boot import make_audition
    from kaine.modules.audition.live import LiveMicConfig

    captured: dict[str, Any] = {}
    original_init = LiveMicConfig.__init__

    def tracking_init(self, *args, **kwargs):
        captured.update(kwargs)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(LiveMicConfig, "__init__", tracking_init)
    monkeypatch.setattr(
        "kaine.boot._build_perception_feed_audio_factory",
        lambda mode, feed_section, **kwargs: lambda: None,
    )

    base_section = {
        "speaches_url": "http://localhost:8080",
        "stt_model": "tiny",
        "emotion_model_id": "emotion2vec",
        "emotion_device": "cpu",
        "request_timeout_s": 10.0,
        "baseline_salience": 0.1,
        "alert_salience": 0.6,
        "capture_enabled": True,
        "capture_sample_rate": 16000,
        "capture_channels": 1,
        "vad_backend": "webrtcvad",
        "vad_aggressiveness": 2,
        "vad_frame_ms": 30,
        "min_utterance_ms": 300,
        "max_utterance_ms": 30000,
        "silence_hangover_ms": 600,
        "desired_state_poll_ms": 250,
    }

    make_audition(bus, {**base_section, "perception_feed": {"mode": "playlist"}})
    assert captured["source_label"] == "playlist"

    captured.clear()
    make_audition(bus, {**base_section, "perception_feed": {"mode": "live"}})
    assert captured["source_label"] == "live_mic"


# ---------------------------------------------------------------------------
# 1.2 Empatheia attribution by channel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empatheia_operator_channels_map_to_speaker(bus):
    emp = Empatheia(bus, store=InMemoryAgentStore())
    await emp.initialize()
    try:
        await emp._handle_emotion(_emotion_event(source_label="live_mic"))
        await emp._handle_emotion(_emotion_event(source_label="remote"))
        await emp._handle_transcription(_transcription_event(source_label="microphone"))
        model = await emp.store.get("operator")
        assert model is not None
        assert model.interaction_count == 3
        # No media agents were created.
        for bad_id in ("media:live_mic", "media:remote", "media:microphone"):
            assert await emp.store.get(bad_id) is None
    finally:
        await emp.shutdown()


@pytest.mark.asyncio
async def test_empatheia_media_channel_maps_to_media_agent(bus):
    emp = Empatheia(bus, store=InMemoryAgentStore())
    await emp.initialize()
    try:
        await emp._handle_emotion(_emotion_event(source_label="playlist"))
        await emp._handle_transcription(_transcription_event(source_label="playlist"))
        model = await emp.store.get("media:playlist")
        assert model is not None
        assert model.interaction_count == 2
        assert await emp.store.get("operator") is None
    finally:
        await emp.shutdown()


@pytest.mark.asyncio
async def test_empatheia_missing_source_label_maps_to_speaker(bus):
    emp = Empatheia(bus, store=InMemoryAgentStore())
    await emp.initialize()
    try:
        await emp._handle_emotion(_emotion_event(source_label=_MISSING))
        await emp._handle_transcription(_transcription_event(source_label=_MISSING))
        model = await emp.store.get("operator")
        assert model is not None
        assert model.interaction_count == 2
        assert await emp.store.get("media:live_mic") is None
    finally:
        await emp.shutdown()


@pytest.mark.asyncio
async def test_empatheia_custom_operator_sources(bus):
    emp = Empatheia(
        bus,
        store=InMemoryAgentStore(),
        operator_sources=["remote"],
        speaker_label="operator",
    )
    await emp.initialize()
    try:
        await emp._handle_emotion(_emotion_event(source_label="remote"))
        await emp._handle_emotion(_emotion_event(source_label="live_mic"))
        op = await emp.store.get("operator")
        media = await emp.store.get("media:live_mic")
        assert op is not None and op.interaction_count == 1
        assert media is not None and media.interaction_count == 1
    finally:
        await emp.shutdown()


# ---------------------------------------------------------------------------
# 1.3 Volition answers only operator-channel speech
# ---------------------------------------------------------------------------


def test_volition_answers_operator_channel():
    policy = DefaultActionSelectionPolicy(clock=FakeClock())
    event = _transcription_event(source_label="live_mic")
    intents = policy(_snapshot(("e1", event)))
    assert len(intents) == 1
    assert intents[0].kind == SPEAK
    assert intents[0].about == "hello world"


def test_volition_ignores_playlist_channel():
    policy = DefaultActionSelectionPolicy(clock=FakeClock())
    event = _transcription_event(source_label="playlist")
    intents = policy(_snapshot(("e1", event)))
    assert intents == []


def test_volition_answers_missing_source_label():
    policy = DefaultActionSelectionPolicy(clock=FakeClock())
    event = _transcription_event(source_label=_MISSING)
    intents = policy(_snapshot(("e1", event)))
    assert len(intents) == 1
    assert intents[0].kind == SPEAK


def test_volition_respects_custom_operator_sources():
    policy = DefaultActionSelectionPolicy(
        clock=FakeClock(), operator_sources=["remote"]
    )
    assert len(policy(_snapshot(("a", _transcription_event(source_label="remote"))))) == 1
    assert policy(_snapshot(("b", _transcription_event(source_label="live_mic")))) == []


def test_drive_biased_policy_forwards_operator_sources():
    policy = DriveBiasedActionSelectionPolicy(
        clock=FakeClock(), operator_sources=["remote"]
    )
    assert len(policy(_snapshot(("a", _transcription_event(source_label="remote"))))) == 1
    assert policy(_snapshot(("b", _transcription_event(source_label="playlist")))) == []


# ---------------------------------------------------------------------------
# 1.4 Vox is dormant in the womb
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vox_dormant_suppresses_output_and_resumes(bus, tmp_path):
    vox, player = _vox_and_player(bus, tmp_path)
    await vox.initialize()
    try:
        assert not vox.dormant
        vox.set_dormant(True)
        assert vox.dormant

        result = await vox.synthesize_text("hello womb")
        assert result.bytes_produced == 0
        assert vox._suppressed_while_dormant == 1
        assert player.played == []
        assert not list((tmp_path / "vox").glob("*.wav"))

        vox.set_dormant(False)
        assert not vox.dormant
        result = await vox.synthesize_text("hello world")
        assert result.bytes_produced == len(b"WAV-FAKE-DATA-1234")
        assert len(player.played) == 1
        assert vox._suppressed_while_dormant == 1  # count does not reset
    finally:
        await vox.shutdown()


def test_gestation_holds_mundus_and_vox_dormant():
    from kaine.cycle.__main__ import _hold_effectors_for_gestation
    from kaine.modules.registry import ModuleRegistry

    class _Effector:
        def __init__(self, name: str) -> None:
            self.name = name
            self.dormant = None

        def set_dormant(self, dormant: bool) -> None:
            self.dormant = dormant

    registry = ModuleRegistry()
    vox, mundus, soma = _Effector("vox"), _Effector("mundus"), _Effector("soma")
    for module in (vox, mundus, soma):
        registry.register(module)

    held = _hold_effectors_for_gestation(registry)

    assert sorted(held) == ["mundus", "vox"]
    assert vox.dormant is True and mundus.dormant is True
    assert soma.dormant is None
