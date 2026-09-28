# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the sherpa-onnx STT/TTS engines using injected fakes."""

from __future__ import annotations

import io
import struct
import sys
import types
import wave
from pathlib import Path

import numpy as np
import pytest

from kaine.modules.audition.sherpa_stt import SherpaMoonshineSTT
from kaine.modules.audition.stt_client import STTClient, TranscriptionResult
from kaine.modules.vox.client import SynthesisResult, TTSClient, TTSRequest
from kaine.modules.vox.sherpa_tts import APPLIED_PROSODY, SherpaKokoroTTS


def _make_wav(rate: int, frames, nchannels: int = 1, sampwidth: int = 2) -> bytes:
    """Encode frames as a WAV blob.  Frames are interleaved samples."""
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


def _fake_sherpa():
    calls: dict[str, list] = {
        "from_moonshine_v2": [],
        "streams": [],
        "generate": [],
    }

    class Stream:
        def __init__(self) -> None:
            self.calls: list[tuple[int, np.ndarray]] = []

        def accept_waveform(self, rate: int, samples: np.ndarray) -> None:
            self.calls.append((rate, samples))

        @property
        def result(self):
            return types.SimpleNamespace(text=" hello world ")

    class Recognizer:
        def __init__(self) -> None:
            pass

        @staticmethod
        def from_moonshine_v2(
            encoder,
            decoder,
            tokens,
            num_threads=1,
            decoding_method="greedy_search",
            debug=False,
            provider="cpu",
        ):
            calls["from_moonshine_v2"].append(
                {
                    "encoder": encoder,
                    "decoder": decoder,
                    "tokens": tokens,
                    "num_threads": num_threads,
                    "decoding_method": decoding_method,
                    "debug": debug,
                    "provider": provider,
                }
            )
            return Recognizer()

        def create_stream(self):
            s = Stream()
            calls["streams"].append(s)
            return s

        def decode_stream(self, _stream) -> None:
            pass

    class KokoroConfig:
        def __init__(
            self,
            model,
            voices,
            tokens,
            lexicon="",
            data_dir="",
            dict_dir="",
            length_scale=1.0,
            lang="",
        ) -> None:
            self.model = model
            self.voices = voices
            self.tokens = tokens
            self.data_dir = data_dir

    class ModelConfig:
        def __init__(
            self,
            kokoro=None,
            num_threads=1,
            debug=False,
            provider="cpu",
        ) -> None:
            self.kokoro = kokoro
            self.num_threads = num_threads

    class TtsConfig:
        def __init__(
            self,
            model,
            rule_fsts="",
            rule_fars="",
            max_num_sentences=1,
            silence_scale=0.2,
        ) -> None:
            self.model = model

    class TtsAudio:
        def __init__(self, samples, sample_rate) -> None:
            self.samples = samples
            self.sample_rate = sample_rate

    class Tts:
        def __init__(self, config) -> None:
            self.config = config

        sample_rate = 24000
        num_speakers = 11

        def generate(self, text: str, sid: int, speed: float):
            calls["generate"].append((text, sid, speed))
            return TtsAudio(
                samples=[0.0, 0.5, -0.5, 1.2],
                sample_rate=24000,
            )

    fake = types.SimpleNamespace(
        OfflineRecognizer=Recognizer,
        OfflineTts=Tts,
        OfflineTtsConfig=TtsConfig,
        OfflineTtsModelConfig=ModelConfig,
        OfflineTtsKokoroModelConfig=KokoroConfig,
    )
    return fake, calls


def _make_stt_dir(root: Path) -> Path:
    d = root / "moonshine-base-en"
    d.mkdir(parents=True)
    for name in ("encoder_model.ort", "decoder_model_merged.ort", "tokens.txt"):
        (d / name).write_bytes(b"")
    return d


def _make_tts_dir(root: Path, missing_espeak: bool = False) -> Path:
    d = root / "kokoro-en"
    d.mkdir(parents=True)
    for name in ("model.int8.onnx", "voices.bin", "tokens.txt"):
        (d / name).write_bytes(b"")
    if not missing_espeak:
        (d / "espeak-ng-data").mkdir()
    return d


def test_stt_construction_is_cheap(tmp_path, monkeypatch):
    calls = []

    class FakeFactory:
        def __init__(self, encoder, decoder, tokens, num_threads):
            calls.append((encoder, decoder, tokens, num_threads))

        @staticmethod
        def from_moonshine_v2(encoder, decoder, tokens, num_threads):
            calls.append((encoder, decoder, tokens, num_threads))
            return FakeFactory(encoder, decoder, tokens, num_threads)

    fake = types.SimpleNamespace(
        OfflineRecognizer=FakeFactory,
    )
    SherpaMoonshineSTT(_make_stt_dir(tmp_path), sherpa_module=fake)
    assert calls == []


@pytest.mark.asyncio
async def test_stt_warm_up_builds_engine(tmp_path):
    fake, calls = _fake_sherpa()
    model_dir = _make_stt_dir(tmp_path)
    stt = SherpaMoonshineSTT(model_dir, sherpa_module=fake)

    await stt.warm_up()
    assert len(calls["from_moonshine_v2"]) == 1
    kwargs = calls["from_moonshine_v2"][0]
    assert kwargs["encoder"] == str(model_dir / "encoder_model.ort")
    assert kwargs["decoder"] == str(model_dir / "decoder_model_merged.ort")
    assert kwargs["tokens"] == str(model_dir / "tokens.txt")
    assert kwargs["num_threads"] == 2


@pytest.mark.asyncio
async def test_stt_warm_up_is_idempotent(tmp_path):
    fake, calls = _fake_sherpa()
    stt = SherpaMoonshineSTT(_make_stt_dir(tmp_path), sherpa_module=fake)

    await stt.warm_up()
    await stt.warm_up()
    assert len(calls["from_moonshine_v2"]) == 1


@pytest.mark.asyncio
async def test_stt_transcribe_calls_warm_up(tmp_path):
    fake, calls = _fake_sherpa()
    stt = SherpaMoonshineSTT(_make_stt_dir(tmp_path), sherpa_module=fake)
    assert not calls["from_moonshine_v2"]

    audio = _make_wav(16000, [0, 1000, -1000])
    res = await stt.transcribe(audio, sample_rate=16000, model="ignored")
    assert res.text == "hello world"
    assert res.model == "moonshine-base-en"
    assert isinstance(res, TranscriptionResult)
    assert len(calls["from_moonshine_v2"]) == 1


@pytest.mark.asyncio
async def test_stt_first_channel_for_stereo(tmp_path):
    fake, calls = _fake_sherpa()
    stt = SherpaMoonshineSTT(_make_stt_dir(tmp_path), sherpa_module=fake)

    # Interleaved stereo frames; only the left channel should reach sherpa.
    audio = _make_wav(16000, [1000, 2000, -1000, -2000, 0, 0], nchannels=2)
    await stt.transcribe(audio, sample_rate=16000, model="ignored")

    stream = calls["streams"][0]
    _, samples = stream.calls[0]
    expected = np.array([1000, -1000, 0], dtype=np.float32) / 32768.0
    assert np.allclose(samples, expected)


@pytest.mark.asyncio
async def test_stt_rejects_8bit_wav(tmp_path):
    fake, _ = _fake_sherpa()
    stt = SherpaMoonshineSTT(_make_stt_dir(tmp_path), sherpa_module=fake)

    audio = _make_wav(16000, [0, 100], sampwidth=1)
    with pytest.raises(ValueError):
        await stt.transcribe(audio, sample_rate=16000, model="ignored")


@pytest.mark.asyncio
async def test_stt_zero_frame_wav_returns_empty(tmp_path):
    fake, calls = _fake_sherpa()
    stt = SherpaMoonshineSTT(_make_stt_dir(tmp_path), sherpa_module=fake)

    audio = _make_wav(16000, [])
    res = await stt.transcribe(audio, sample_rate=16000, model="ignored")
    assert res.text == ""
    assert res.model == "moonshine-base-en"
    assert not calls["streams"]


def test_stt_raises_file_not_found_for_missing_model(tmp_path):
    fake, _ = _fake_sherpa()
    partial = tmp_path / "moonshine-base-en"
    partial.mkdir()
    (partial / "encoder_model.ort").write_bytes(b"")
    (partial / "tokens.txt").write_bytes(b"")

    with pytest.raises(FileNotFoundError) as exc_info:
        SherpaMoonshineSTT(partial, sherpa_module=fake)
    assert "python -m kaine.setup.speech_models --stt moonshine-base-en" in str(
        exc_info.value
    )


def test_stt_raises_import_error_without_sherpa_onnx(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "sherpa_onnx", None)
    # Provide all files so the missing-file check passes; only the import fails.
    model_dir = _make_stt_dir(tmp_path)
    with pytest.raises(ImportError, match="speech-edge"):
        SherpaMoonshineSTT(model_dir)


@pytest.mark.asyncio
async def test_stt_raises_after_aclose(tmp_path):
    fake, _ = _fake_sherpa()
    stt = SherpaMoonshineSTT(_make_stt_dir(tmp_path), sherpa_module=fake)
    await stt.aclose()

    audio = _make_wav(16000, [0, 1000, -1000])
    with pytest.raises(RuntimeError, match="sherpa-onnx STT client is closed"):
        await stt.transcribe(audio, sample_rate=16000, model="ignored")


@pytest.mark.asyncio
async def test_tts_construction_is_cheap(tmp_path, monkeypatch):
    calls = []

    class FakeTts:
        def __init__(self, config):
            self.config = config
        sample_rate = 24000
        num_speakers = 11

    fake = types.SimpleNamespace(
        OfflineTts=FakeTts,
        OfflineTtsConfig=lambda config: config,
        OfflineTtsModelConfig=lambda **kw: types.SimpleNamespace(**kw),
        OfflineTtsKokoroModelConfig=lambda **kw: types.SimpleNamespace(**kw),
    )

    SherpaKokoroTTS(_make_tts_dir(tmp_path), sherpa_module=fake)
    assert calls == []


@pytest.mark.asyncio
async def test_tts_warm_up_builds_engine(tmp_path):
    fake, calls = _fake_sherpa()
    model_dir = _make_tts_dir(tmp_path)
    tts = SherpaKokoroTTS(model_dir, sherpa_module=fake)

    await tts.warm_up()
    cfg = tts._tts.config
    assert cfg.model.num_threads == 2
    kokoro = cfg.model.kokoro
    assert kokoro.model == str(model_dir / "model.int8.onnx")
    assert kokoro.voices == str(model_dir / "voices.bin")
    assert kokoro.tokens == str(model_dir / "tokens.txt")
    assert kokoro.data_dir == str(model_dir / "espeak-ng-data")


@pytest.mark.asyncio
async def test_tts_warm_up_is_idempotent(tmp_path):
    fake, calls = _fake_sherpa()
    tts = SherpaKokoroTTS(_make_tts_dir(tmp_path), sherpa_module=fake)

    await tts.warm_up()
    await tts.warm_up()
    assert len(calls["generate"]) == 0


@pytest.mark.asyncio
async def test_tts_synthesize_calls_warm_up(tmp_path):
    fake, calls = _fake_sherpa()
    tts = SherpaKokoroTTS(_make_tts_dir(tmp_path), sherpa_module=fake)
    assert tts._tts is None

    res = await tts.synthesize(TTSRequest(text="hello"))
    assert res.content_type == "audio/wav"
    assert res.output_format == "wav"
    assert res.bytes_produced == len(res.audio)
    assert isinstance(res, SynthesisResult)
    assert len(calls["generate"]) == 1


@pytest.mark.asyncio
async def test_tts_speed_clamping(tmp_path):
    fake, calls = _fake_sherpa()
    tts = SherpaKokoroTTS(_make_tts_dir(tmp_path), sherpa_module=fake)

    await tts.synthesize(TTSRequest(text="fast", speed_factor=5.0))
    assert calls["generate"][-1] == ("fast", 0, 2.0)

    await tts.synthesize(TTSRequest(text="slow", speed_factor=float("nan")))
    assert calls["generate"][-1] == ("slow", 0, 1.0)


@pytest.mark.asyncio
async def test_tts_rejects_empty_text(tmp_path):
    fake, _ = _fake_sherpa()
    tts = SherpaKokoroTTS(_make_tts_dir(tmp_path), sherpa_module=fake)

    with pytest.raises(ValueError, match="empty text"):
        await tts.synthesize(TTSRequest(text="   "))


@pytest.mark.asyncio
async def test_tts_raises_after_aclose(tmp_path):
    fake, _ = _fake_sherpa()
    tts = SherpaKokoroTTS(_make_tts_dir(tmp_path), sherpa_module=fake)
    await tts.aclose()

    with pytest.raises(RuntimeError, match="sherpa-onnx TTS client is closed"):
        await tts.synthesize(TTSRequest(text="hello"))


@pytest.mark.asyncio
async def test_tts_rejects_out_of_range_speaker(tmp_path):
    fake, _ = _fake_sherpa()
    model_dir = _make_tts_dir(tmp_path)
    tts = SherpaKokoroTTS(model_dir, speaker_id=11, sherpa_module=fake)
    with pytest.raises(ValueError, match="speaker_id 11"):
        await tts.warm_up()


def test_tts_raises_file_not_found_for_missing_espeak(tmp_path):
    fake, _ = _fake_sherpa()
    model_dir = _make_tts_dir(tmp_path, missing_espeak=True)
    with pytest.raises(FileNotFoundError):
        SherpaKokoroTTS(model_dir, sherpa_module=fake)


def test_tts_raises_import_error_without_sherpa_onnx(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "sherpa_onnx", None)
    model_dir = _make_tts_dir(tmp_path)
    with pytest.raises(ImportError, match="speech-edge"):
        SherpaKokoroTTS(model_dir)


def test_tts_applied_prosody_constant():
    assert APPLIED_PROSODY == ("speed_factor",)


def test_protocol_membership(tmp_path):
    fake, _ = _fake_sherpa()
    stt = SherpaMoonshineSTT(_make_stt_dir(tmp_path), sherpa_module=fake)
    tts = SherpaKokoroTTS(_make_tts_dir(tmp_path), sherpa_module=fake)
    assert isinstance(stt, STTClient)
    assert isinstance(tts, TTSClient)


@pytest.mark.asyncio
async def test_aclose_is_idempotent(tmp_path):
    fake, _ = _fake_sherpa()
    stt = SherpaMoonshineSTT(_make_stt_dir(tmp_path), sherpa_module=fake)
    tts = SherpaKokoroTTS(_make_tts_dir(tmp_path), sherpa_module=fake)

    await stt.aclose()
    await stt.aclose()

    await tts.aclose()
    await tts.aclose()
