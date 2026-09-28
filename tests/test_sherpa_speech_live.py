# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Live integration tests for the real sherpa-onnx speech backends.

These tests exercise the actual sherpa-onnx wheels and the pinned model weights
under ``$KAINE_MODELS_DIR``.  They skip cleanly when the optional dependency or
the models are not installed.
"""

import io
import json
import struct
import wave

import numpy as np
import pytest

sherpa_onnx = pytest.importorskip(
    "sherpa_onnx", reason="speech-edge extra not installed"
)

from kaine.boot import make_audition, make_vox  # noqa: E402
from kaine.bus.client import AsyncBus  # noqa: E402
from kaine.bus.config import BusConfig  # noqa: E402
from kaine.modules.audition.sherpa_stt import SherpaMoonshineSTT  # noqa: E402
from kaine.modules.vox.client import TTSRequest  # noqa: E402
from kaine.modules.vox.playback import FakePlayer  # noqa: E402
from kaine.modules.vox.sherpa_tts import SherpaKokoroTTS  # noqa: E402
from kaine.nexus.health.probes import (  # noqa: E402
    UP,
    clear_sherpa_probe_memo,
    probe_sherpa_stt,
    probe_sherpa_tts,
)
from kaine.setup.speech_models import is_installed, model_dir  # noqa: E402


def _require_models() -> None:
    missing = [
        m for m in ("moonshine-base-en", "kokoro-en") if not is_installed(m)
    ]
    if missing:
        pytest.skip(
            "Missing sherpa-onnx speech models; run "
            "`python -m kaine.setup.speech_models`"
        )


def _normalize(text: str) -> str:
    lowered = text.lower()
    keep = "".join(ch if ch.isalpha() or ch == " " else " " for ch in lowered)
    return " ".join(keep.split())


def _word_coverage(expected: str, actual: str, threshold: int = 7) -> bool:
    expected_words = set(_normalize(expected).split())
    actual_words = set(_normalize(actual).split())
    return len(expected_words & actual_words) >= threshold


def _wav_sample_rate(wav: bytes) -> int:
    with wave.open(io.BytesIO(wav), "rb") as wf:
        return wf.getframerate()


def _silence_frames(seconds: float, sr: int = 16000) -> list[int]:
    return np.zeros(int(seconds * sr), dtype=np.int16).tolist()


def _make_wav(rate: int, frames, nchannels: int = 1, sampwidth: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(nchannels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(rate)
        if sampwidth == 1:
            packed = bytes(max(0, min(255, int(s) + 128)) for s in frames)
        else:
            packed = struct.pack(f"<{len(frames)}h", *frames)
        wf.writeframes(packed)
    return buf.getvalue()


def _decode_payload(raw):
    if isinstance(raw, (str, bytes)):
        try:
            return json.loads(raw)
        except Exception:
            pass
    return raw


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


@pytest.mark.asyncio
async def test_engine_round_trip():
    _require_models()
    tts = SherpaKokoroTTS(model_dir("kokoro-en"))
    stt = SherpaMoonshineSTT(model_dir("moonshine-base-en"))
    try:
        request = TTSRequest(text="The quick brown fox jumps over the lazy dog.")
        wav = (await tts.synthesize(request)).audio
        assert wav.startswith(b"RIFF")
        sample_rate = _wav_sample_rate(wav)
        result = await stt.transcribe(
            wav, sample_rate=sample_rate, model="moonshine-base-en"
        )
        assert result is not None
        assert _word_coverage(
            "The quick brown fox jumps over the lazy dog.",
            result.text,
            threshold=7,
        )
    finally:
        await tts.aclose()
        await stt.aclose()


@pytest.mark.asyncio
async def test_module_round_trip_with_disclosure(bus):
    _require_models()

    vox = make_vox(
        bus,
        {
            "backend": "sherpa_onnx",
            "playback_enabled": True,
        },
    )
    assert vox is not None
    vox._player = FakePlayer()

    audition = make_audition(
        bus,
        {
            "backend": "sherpa_onnx",
            "transcription_enabled": True,
            "emotion_model_id": "",
        },
    )
    assert audition is not None

    try:
        await vox.initialize()
        await audition.initialize()

        await vox.synthesize_text("Hello from the edge.")

        assert vox._player.played
        wav = vox._player.played[0]
        sample_rate = _wav_sample_rate(wav)

        await audition.process_audio(
            wav, sample_rate, source_label="test"
        )

        vox_entries = await bus.read("vox.out", last_id="0", count=50)
        vox_payload = None
        for _id, event in vox_entries:
            if event.type == "vox.synthesized":
                vox_payload = _decode_payload(event.payload)
                break
        assert vox_payload is not None

        assert vox_payload["backend"] == "sherpa_onnx"
        assert vox_payload["prosody_applied"] == ["speed_factor"]
        assert vox_payload["voice"] == "kokoro-en speaker 0"

        audition_entries = await bus.read("audition.out", last_id="0", count=50)
        transcription_payload = None
        for _id, event in audition_entries:
            if event.type == "audition.transcription":
                transcription_payload = _decode_payload(event.payload)
                break
        assert transcription_payload is not None

        assert transcription_payload["backend"] == "sherpa_onnx"
        assert "error" not in transcription_payload
        assert "hello" in transcription_payload.get("text", "").lower()
    finally:
        await vox.shutdown()
        await audition.shutdown()


@pytest.mark.asyncio
async def test_health_probes():
    _require_models()
    clear_sherpa_probe_memo()

    stt_status, _ = await probe_sherpa_stt(
        model_dir=str(model_dir("moonshine-base-en")),
        model_id="moonshine-base-en",
        num_threads=2,
    )
    assert stt_status == UP

    tts_status, _ = await probe_sherpa_tts(
        model_dir=str(model_dir("kokoro-en")),
        model_id="kokoro-en",
        speaker_id=0,
        num_threads=2,
    )
    assert tts_status == UP

    clear_sherpa_probe_memo()


@pytest.mark.asyncio
async def test_silence():
    _require_models()
    stt = SherpaMoonshineSTT(model_dir("moonshine-base-en"))
    try:
        wav = _make_wav(16000, _silence_frames(0.5, 16000))
        result = await stt.transcribe(
            wav, sample_rate=16000, model="moonshine-base-en"
        )
        assert (result.text or "").strip() == ""
    finally:
        await stt.aclose()
