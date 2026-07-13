# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import asyncio
import io
import os
import wave

import numpy as np
import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.audition import (
    Audition,
    CATEGORIES,
    EmotionResult,
    FakeEmotionClassifier,
    FakeSTTClient,
)
from kaine.modules.audition.acoustic import FakeAcousticEncoder


def _tone(
    freq: float, seconds: float = 0.2, amp: float = 0.3, sr: int = 16000
) -> bytes:
    t = np.arange(int(seconds * sr)) / sr
    return (amp * np.sin(2 * np.pi * freq * t) * 32767).astype("<i2").tobytes()


def _silence(seconds: float = 0.2, sr: int = 16000) -> bytes:
    return np.zeros(int(seconds * sr), dtype="<i2").tobytes()


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _make_audition(bus: AsyncBus, **overrides) -> Audition:
    return Audition(
        bus,
        stt_client=FakeSTTClient(responses=["hello world"]),
        emotion_classifier=FakeEmotionClassifier(),
        stt_model="fake-stt",
        **overrides,
    )


@pytest.mark.asyncio
async def test_invalid_construction(bus: AsyncBus):
    with pytest.raises(ValueError):
        Audition(bus, stt_client=FakeSTTClient(), baseline_salience=2.0)
    with pytest.raises(ValueError):
        Audition(bus, stt_client=FakeSTTClient(), alert_salience=-0.1)


@pytest.mark.asyncio
async def test_process_audio_publishes_two_events(bus: AsyncBus):
    audition = _make_audition(bus)
    await audition.initialize()
    try:
        await audition.process_audio(b"\x00" * 1024, sample_rate=16000)
        entries = await bus.read("audition.out", last_id="0", count=10)
        types = sorted(e.type for _, e in entries)
        assert types == ["audition.emotion", "audition.transcription"]
    finally:
        await audition.shutdown()


@pytest.mark.asyncio
async def test_transcription_gate_off_publishes_no_transcript(bus: AsyncBus):
    """transcription_enabled=false: no audition.transcription and no STT call —
    the entity hears sound as prediction error, not a transcript (the STT-ectomy).
    Emotion (an affect signal) is unaffected."""

    class _RecordingSTT(FakeSTTClient):
        def __init__(self):
            super().__init__(responses=["should not run"])
            self.calls = 0

        async def transcribe(self, *a, **k):
            self.calls += 1
            return await super().transcribe(*a, **k)

    stt = _RecordingSTT()
    audition = Audition(
        bus,
        stt_client=stt,
        emotion_classifier=FakeEmotionClassifier(),
        stt_model="fake-stt",
        transcription_enabled=False,
    )
    await audition.initialize()
    try:
        await audition.process_audio(b"\x00" * 1024, sample_rate=16000)
        entries = await bus.read("audition.out", last_id="0", count=10)
        types = {e.type for _, e in entries}
        assert "audition.transcription" not in types  # no transcript
        assert "audition.emotion" in types  # affect signal unaffected
        assert stt.calls == 0  # STT model never invoked
    finally:
        await audition.shutdown()


@pytest.mark.asyncio
async def test_transcription_payload_shape(bus: AsyncBus):
    audition = _make_audition(bus)
    await audition.initialize()
    try:
        await audition.process_audio(
            b"\x00" * 4096, sample_rate=24000, source_label="mic1"
        )
        entries = await bus.read("audition.out", last_id="0", count=10)
        trans = next(e for _, e in entries if e.type == "audition.transcription")
        for key in (
            "text",
            "source_label",
            "model",
            "sample_rate",
            "audio_bytes_length",
            "latency_ms",
        ):
            assert key in trans.payload
        assert trans.payload["text"] == "hello world"
        assert trans.payload["source_label"] == "mic1"
        assert trans.payload["sample_rate"] == 24000
        assert trans.payload["audio_bytes_length"] == 4096
    finally:
        await audition.shutdown()


@pytest.mark.asyncio
async def test_emotion_payload_shape(bus: AsyncBus):
    audition = _make_audition(bus)
    await audition.initialize()
    try:
        await audition.process_audio(b"\x00", sample_rate=16000)
        entries = await bus.read("audition.out", last_id="0", count=10)
        emo = next(e for _, e in entries if e.type == "audition.emotion")
        for key in (
            "category",
            "confidence",
            "scores",
            "model",
            "source_label",
            "latency_ms",
        ):
            assert key in emo.payload
        assert emo.payload["category"] in CATEGORIES
    finally:
        await audition.shutdown()


@pytest.mark.asyncio
async def test_stt_failure_still_publishes_emotion(bus: AsyncBus):
    class FailingSTT(FakeSTTClient):
        async def transcribe(
            self, audio_bytes, *, sample_rate, model, filename="audio.wav"
        ):
            raise RuntimeError("boom")

    audition = Audition(
        bus,
        stt_client=FailingSTT(),
        emotion_classifier=FakeEmotionClassifier(),
        stt_model="fake-stt",
    )
    await audition.initialize()
    try:
        await audition.process_audio(b"\x00", sample_rate=16000)
        entries = await bus.read("audition.out", last_id="0", count=10)
        types = sorted(e.type for _, e in entries)
        assert types == ["audition.emotion", "audition.transcription"]
        trans = next(e for _, e in entries if e.type == "audition.transcription")
        assert trans.payload["text"] == ""
        assert "error" in trans.payload
    finally:
        await audition.shutdown()


@pytest.mark.asyncio
async def test_emotion_failure_still_publishes_transcription(bus: AsyncBus):
    class FailingEmo(FakeEmotionClassifier):
        async def classify(self, audio_bytes, *, sample_rate):
            raise RuntimeError("ema fail")

    audition = Audition(
        bus,
        stt_client=FakeSTTClient(responses=["text"]),
        emotion_classifier=FailingEmo(),
        stt_model="fake-stt",
    )
    await audition.initialize()
    try:
        await audition.process_audio(b"\x00", sample_rate=16000)
        entries = await bus.read("audition.out", last_id="0", count=10)
        emo = next(e for _, e in entries if e.type == "audition.emotion")
        assert emo.payload["category"] == "neutral"
        assert "error" in emo.payload
    finally:
        await audition.shutdown()


@pytest.mark.asyncio
async def test_non_neutral_emotion_raises_salience(bus: AsyncBus):
    happy = EmotionResult(
        category="happy",
        confidence=0.9,
        scores={c: (0.9 if c == "happy" else 0.0) for c in CATEGORIES},
        model="fake",
        latency_ms=1.0,
    )
    audition = Audition(
        bus,
        stt_client=FakeSTTClient(),
        emotion_classifier=FakeEmotionClassifier(results=[happy]),
        stt_model="fake-stt",
    )
    await audition.initialize()
    try:
        await audition.process_audio(b"\x00", sample_rate=16000)
        entries = await bus.read("audition.out", last_id="0", count=10)
        emo = next(e for _, e in entries if e.type == "audition.emotion")
        assert emo.salience == pytest.approx(audition._alert_salience)
    finally:
        await audition.shutdown()


@pytest.mark.asyncio
async def test_serialize_yields_model_ids(bus: AsyncBus):
    audition = _make_audition(bus)
    state = audition.serialize()
    assert state["stt_model"] == "fake-stt"
    assert state["emotion_model_id"] == "fake/emotion"


# ---------------------------------------------------------------------------
# Forward model: serialize includes buffer_summary with no raw data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_serialize_includes_forward_model_state(bus: AsyncBus):
    audition = _make_audition(bus)
    await audition.initialize()
    try:
        await audition.process_audio(b"\x00" * 1024, sample_rate=16000)
        state = audition.serialize()
        assert "forward_model" in state
        assert "auditory_buffer_summary" in state
        # Buffer summary must contain only numeric fields (no bytes).
        summary = state["auditory_buffer_summary"]
        assert "n_utterances" in summary
        assert "mean" in summary
        assert "variance" in summary
        for v in summary["mean"]:
            assert isinstance(v, float)
        for v in summary["variance"]:
            assert isinstance(v, float)
    finally:
        await audition.shutdown()


@pytest.mark.asyncio
async def test_forward_model_state_no_raw_tensors(bus: AsyncBus):
    """serialize() forward_model must contain no bytes or torch.Tensor values."""
    import torch

    audition = _make_audition(bus)
    await audition.initialize()
    try:
        await audition.process_audio(b"\x00" * 1024, sample_rate=16000)
        state = audition.serialize()

        def _no_tensors(obj, path="root"):
            if isinstance(obj, torch.Tensor):
                raise AssertionError(f"Tensor at {path}")
            if isinstance(obj, bytes):
                raise AssertionError(f"bytes at {path}")
            if isinstance(obj, dict):
                for k, v in obj.items():
                    _no_tensors(v, f"{path}[{k!r}]")
            elif isinstance(obj, (list, tuple)):
                for i, v in enumerate(obj):
                    _no_tensors(v, f"{path}[{i}]")

        _no_tensors(state)
    finally:
        await audition.shutdown()


# ---------------------------------------------------------------------------
# Prosody: audition.prosody published when enabled; no bytes in payload
# ---------------------------------------------------------------------------


def _make_wav_bytes(n_samples: int = 1600, sample_rate: int = 16000) -> bytes:
    """Build a minimal silent WAV blob in memory."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * n_samples)
    return buf.getvalue()


@pytest.mark.asyncio
def _fake_extract_prosody(audio, *, sample_rate: int = 16000):
    """Deterministic stand-in for the real librosa/pyin extractor.

    The real ``extract_prosody`` runs pyin on a thread pool — slow (1-2 s cold)
    and env-dependent (silent CI runs timed out or produced nothing). STT and
    emotion are already faked here; faking prosody the same way makes the publish
    path deterministic and fast without depending on the audio stack (#67)."""
    return {
        "f0_mean_hz": 120.0,
        "f0_std_hz": 5.0,
        "f0_voiced_frac": 0.8,
        "rms_mean": 0.1,
        "rms_std": 0.02,
        "tempo_bpm": 90.0,
    }


async def test_prosody_published_when_enabled(bus: AsyncBus, monkeypatch):
    """When prosody_enabled=True, an audition.prosody event is published."""
    monkeypatch.setattr(
        "kaine.modules.audition.prosody.extract_prosody", _fake_extract_prosody
    )
    audition = Audition(
        bus,
        stt_client=FakeSTTClient(responses=["hi"]),
        emotion_classifier=FakeEmotionClassifier(),
        stt_model="fake-stt",
        prosody_enabled=True,
    )
    await audition.initialize()
    try:
        wav = _make_wav_bytes(n_samples=16000)  # 1 second of silence
        await audition.process_audio(wav, sample_rate=16000)
        # Prosody is published from a thread; poll briefly (the fake is instant).
        deadline = asyncio.get_event_loop().time() + 5.0
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.1)
            entries = await bus.read("audition.out", last_id="0", count=20)
            types = [e.type for _, e in entries]
            if "audition.prosody" in types:
                break
        else:
            entries = await bus.read("audition.out", last_id="0", count=20)
            types = [e.type for _, e in entries]
        assert "audition.prosody" in types, (
            f"Expected audition.prosody in bus events; got {types}"
        )
    finally:
        await audition.shutdown()


@pytest.mark.asyncio
async def test_prosody_payload_no_bytes(bus: AsyncBus, monkeypatch):
    """audition.prosody payload must contain no bytes values."""
    monkeypatch.setattr(
        "kaine.modules.audition.prosody.extract_prosody", _fake_extract_prosody
    )
    audition = Audition(
        bus,
        stt_client=FakeSTTClient(responses=["hi"]),
        emotion_classifier=FakeEmotionClassifier(),
        stt_model="fake-stt",
        prosody_enabled=True,
    )
    await audition.initialize()
    try:
        wav = _make_wav_bytes(n_samples=16000)
        await audition.process_audio(wav, sample_rate=16000)
        # Poll up to 5 s for the prosody task to complete.
        deadline = asyncio.get_event_loop().time() + 5.0
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.1)
            entries = await bus.read("audition.out", last_id="0", count=20)
            if any(e.type == "audition.prosody" for _, e in entries):
                break
        prosody_events = [e for _, e in entries if e.type == "audition.prosody"]
        assert prosody_events, "Expected at least one audition.prosody event"
        for ev in prosody_events:
            for key, val in ev.payload.items():
                assert not isinstance(val, (bytes, bytearray)), (
                    f"bytes value in audition.prosody payload at '{key}'"
                )
    finally:
        await audition.shutdown()


@pytest.mark.asyncio
async def test_prosody_not_published_when_disabled(bus: AsyncBus):
    """When prosody_enabled=False (default), no audition.prosody event is published."""
    audition = _make_audition(bus)  # prosody_enabled defaults to False
    await audition.initialize()
    try:
        await audition.process_audio(b"\x00" * 1024, sample_rate=16000)
        await asyncio.sleep(0.1)
        entries = await bus.read("audition.out", last_id="0", count=20)
        types = [e.type for _, e in entries]
        assert "audition.prosody" not in types, (
            f"audition.prosody must not be published when disabled; got {types}"
        )
    finally:
        await audition.shutdown()


# ---------------------------------------------------------------------------
# Zero-persistence: no raw audio written to disk
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_zero_persistence_no_named_temp_file(bus: AsyncBus, monkeypatch):
    """process_audio must never call tempfile.NamedTemporaryFile."""
    import tempfile

    calls: list[str] = []
    original = tempfile.NamedTemporaryFile

    def _spy(*args, **kwargs):
        calls.append("called")
        return original(*args, **kwargs)

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", _spy)

    audition = _make_audition(bus)
    await audition.initialize()
    try:
        await audition.process_audio(b"\x00" * 1024, sample_rate=16000)
    finally:
        await audition.shutdown()

    assert calls == [], (
        "NamedTemporaryFile was called during process_audio — zero-persistence violated"
    )


REAL_AUDIO_IN_ENV = "KAINE_AUDIO_IN_RUN_REAL"


@pytest.mark.skipif(
    os.environ.get(REAL_AUDIO_IN_ENV) != "1",
    reason=f"set {REAL_AUDIO_IN_ENV}=1 to hit live Speaches",
)
@pytest.mark.asyncio
async def test_real_speaches_transcribes(bus: AsyncBus):
    """Hits Speaches at 127.0.0.1:8000. Operator must have started it.

    Speaches returns 404 if the requested model is not the one it has loaded
    (the same failure an stt_model mismatch causes at boot). Discover a served
    whisper model from /v1/models rather than hardcoding, so this validates
    transcription against whatever the operator's Speaches actually serves;
    skip if it exposes no whisper STT model.
    """
    import httpx

    from kaine.modules.audition.stt_client import SpeachesClient

    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8000", timeout=15.0
    ) as probe:
        resp = await probe.get("/v1/models")
        resp.raise_for_status()
        served = [m.get("id", "") for m in resp.json().get("data", [])]
    whisper = [m for m in served if "whisper" in m.lower()]
    if not whisper:
        pytest.skip(f"Speaches serves no whisper STT model (has: {served})")
    model_id = whisper[0]

    # Generate a 1-second silent WAV at 16kHz.
    import struct

    n = 16000
    header = (
        b"RIFF"
        + struct.pack("<I", 36 + n * 2)
        + b"WAVE"
        + b"fmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16)
        + b"data"
        + struct.pack("<I", n * 2)
    )
    silent = header + b"\x00\x00" * n
    client = SpeachesClient()
    try:
        result = await client.transcribe(silent, sample_rate=16000, model=model_id)
        assert isinstance(result.text, str)  # may be empty for silence
    finally:
        await client.aclose()


# --------------------------------------------------------------------------- #
# General auditory perception (auditory-perception)
# --------------------------------------------------------------------------- #


def _general_audition(bus: AsyncBus, **overrides) -> Audition:
    return _make_audition(
        bus,
        general_audition=True,
        acoustic_encoder=FakeAcousticEncoder(embedding_dim=8),
        **overrides,
    )


@pytest.mark.asyncio
async def test_general_audition_off_publishes_no_perception_event(bus: AsyncBus):
    audition = _make_audition(bus)  # default: general_audition off
    await audition.initialize()
    try:
        await audition.process_audio(_tone(300), sample_rate=16000)
        entries = await bus.read("audition.out", last_id="0", count=10)
        assert not any(e.type == "audition.perception" for _, e in entries)
    finally:
        await audition.shutdown()


@pytest.mark.asyncio
async def test_general_audition_perceives_non_speech_without_transcribing(
    bus: AsyncBus,
):
    audition = _general_audition(bus)
    await audition.initialize()
    try:
        # A 7 kHz tone is not speech -> perceived acoustically, no STT/emotion.
        await audition.process_audio(_tone(7000), sample_rate=16000)
        entries = await bus.read("audition.out", last_id="0", count=10)
        types = {e.type for _, e in entries}
        assert "audition.perception" in types
        assert "audition.transcription" not in types
        assert "audition.emotion" not in types
    finally:
        await audition.shutdown()


@pytest.mark.asyncio
async def test_general_audition_speech_runs_the_speech_specialization(bus: AsyncBus):
    audition = _general_audition(bus)
    await audition.initialize()
    try:
        # A 300 Hz tone with energy is in the speech band -> perception + speech.
        await audition.process_audio(_tone(300), sample_rate=16000)
        entries = await bus.read("audition.out", last_id="0", count=10)
        types = {e.type for _, e in entries}
        assert {
            "audition.perception",
            "audition.transcription",
            "audition.emotion",
        } <= types
    finally:
        await audition.shutdown()


@pytest.mark.asyncio
async def test_perception_event_is_content_free(bus: AsyncBus):
    audition = _general_audition(bus)
    await audition.initialize()
    try:
        await audition.process_audio(_tone(7000), sample_rate=16000)
        entries = await bus.read("audition.out", last_id="0", count=10)
        perc = next(e for _, e in entries if e.type == "audition.perception")
        assert set(perc.payload) == {
            "source_label",
            "change_score",
            "prediction_error",
            "encoder_model_id",
            "attended_window",
            "alert",
        }
        # numeric metadata only — no audio bytes anywhere in the payload
        for v in perc.payload.values():
            assert not isinstance(v, (bytes, bytearray))
    finally:
        await audition.shutdown()


@pytest.mark.asyncio
async def test_arousal_provider_narrows_the_auditory_window(bus: AsyncBus):
    async def _window_at(arousal: float) -> float:
        b = pytest.importorskip("fakeredis.aioredis")
        client = b.FakeRedis(decode_responses=True)
        local = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
        audition = _general_audition(local)
        audition.set_arousal_provider(lambda: arousal)
        await audition.initialize()
        try:
            await audition.process_audio(_tone(7000), sample_rate=16000)
            entries = await local.read("audition.out", last_id="0", count=10)
            perc = next(e for _, e in entries if e.type == "audition.perception")
            return perc.payload["attended_window"]
        finally:
            await audition.shutdown()
            await local.close()

    calm = await _window_at(0.0)
    tense = await _window_at(1.0)
    assert tense < calm  # Easterbrook: higher arousal -> tighter window


class _ConstErrorForwardModel:
    """Test double: constant prediction error, isolating the change-alert path
    from the forward-model path (normalised error stays ~1.0 → never alerts)."""

    def step(self, embedding):  # noqa: ARG002
        return 1.0


@pytest.mark.asyncio
async def test_acoustic_onset_alerts_relative_to_baseline(bus: AsyncBus):
    """Self-calibrating acoustic alert (perception-drives-salience): an onset —
    change far above the module's own rolling baseline — alerts; steady sound
    stays at baseline. The threshold is a small floor, not an absolute gate."""
    audition = _general_audition(bus, acoustic_change_alert_threshold=0.01)
    audition._acoustic_forward_model = _ConstErrorForwardModel()
    await audition.initialize()
    try:
        steady = _tone(300)
        onset = _tone(6000)  # very different bytes → near-orthogonal embedding
        for _ in range(4):
            await audition.process_audio(steady, sample_rate=16000)
        await audition.process_audio(onset, sample_rate=16000)
        entries = await bus.read("audition.out", last_id="0", count=50)
        perc = [e for _, e in entries if e.type == "audition.perception"]
        assert len(perc) == 5
        # The four steady windows stay at baseline; the onset alerts.
        assert all(p.payload["alert"] is False for p in perc[:4])
        assert perc[4].payload["alert"] is True
        assert perc[4].salience == pytest.approx(audition._alert_salience)
    finally:
        await audition.shutdown()


@pytest.mark.asyncio
async def test_acoustic_change_alert_stats(bus: AsyncBus):
    """Cumulative acoustic alert counts are tracked for run visibility (task 4.2)."""
    audition = _general_audition(bus, acoustic_change_alert_threshold=0.01)
    audition._acoustic_forward_model = _ConstErrorForwardModel()
    await audition.initialize()
    try:
        for _ in range(3):
            await audition.process_audio(_tone(300), sample_rate=16000)
        await audition.process_audio(_tone(6000), sample_rate=16000)
        assert audition._acoustic_report_count == 4
        assert audition._acoustic_alert_count == 1
    finally:
        await audition.shutdown()
