# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for reversible unload/load of the sherpa-onnx speech engines."""

from __future__ import annotations

import asyncio
import io
import struct
import threading
import types
import wave
import weakref
from pathlib import Path

import pytest

from kaine.modules.audition.sherpa_stt import SherpaMoonshineSTT as _SherpaMoonshineSTT
from kaine.modules.vox.client import TTSRequest
from kaine.modules.vox.sherpa_tts import SherpaKokoroTTS as _SherpaKokoroTTS


class SherpaMoonshineSTT(_SherpaMoonshineSTT):
    """Test wrapper: skip on-disk verification."""
    def __init__(self, *args, _verify: bool = False, **kwargs):
        super().__init__(*args, _verify=_verify, **kwargs)


class SherpaKokoroTTS(_SherpaKokoroTTS):
    """Test wrapper: skip on-disk verification."""
    def __init__(self, *args, _verify: bool = False, **kwargs):
        super().__init__(*args, _verify=_verify, **kwargs)


def _stt_dir(tmp_path: Path, *, tokens: str = "a 0\n") -> Path:
    d = tmp_path / "stt"
    d.mkdir()
    (d / "encoder_model.ort").write_text("x", encoding="utf-8")
    (d / "decoder_model_merged.ort").write_text("x", encoding="utf-8")
    (d / "tokens.txt").write_text(tokens, encoding="utf-8")
    return d


def _tts_dir(tmp_path: Path) -> Path:
    d = tmp_path / "tts"
    d.mkdir()
    for name in ("model.int8.onnx", "voices.bin", "tokens.txt"):
        (d / name).write_text("x", encoding="utf-8")
    (d / "espeak-ng-data").mkdir()
    return d


def _make_wav(rate: int, frames, nchannels: int = 1, sampwidth: int = 2) -> bytes:
    """Encode frames as a WAV blob."""
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


def _fake_stt_module(
    text: str = "hello world",
    *,
    block_event: threading.Event | None = None,
    started_event: asyncio.Event | None = None,
):
    loop = asyncio.get_running_loop()

    class Stream:
        def __init__(self) -> None:
            self.result = types.SimpleNamespace(text=text)

        def accept_waveform(self, rate, samples) -> None:  # noqa: ARG002
            pass

    class Recognizer:
        def create_stream(self) -> Stream:
            return Stream()

        def decode_stream(self, stream: Stream) -> None:  # noqa: ARG002
            if started_event is not None:
                loop.call_soon_threadsafe(started_event.set)
            if block_event is not None:
                block_event.wait()

    class OfflineRecognizer:
        @staticmethod
        def from_moonshine_v2(*args, **kwargs):  # noqa: ARG004
            return Recognizer()

    return types.SimpleNamespace(OfflineRecognizer=OfflineRecognizer)


def _fake_tts_module(
    *,
    block_event: threading.Event | None = None,
    started_event: asyncio.Event | None = None,
    sample_rate: int = 24000,
):
    loop = asyncio.get_running_loop()

    class OfflineTtsKokoroModelConfig:
        def __init__(self, **kwargs):  # noqa: ARG002
            pass

    class OfflineTtsModelConfig:
        def __init__(self, *, kokoro, num_threads):  # noqa: ARG002
            pass

    class OfflineTtsConfig:
        def __init__(self, *, model):  # noqa: ARG002
            pass

    class OfflineTts:
        num_speakers = 10

        def __init__(self, config):  # noqa: ARG002 - matches sherpa's OfflineTts(config)
            pass

        def generate(self, text, sid, speed):  # noqa: ARG002
            if started_event is not None:
                loop.call_soon_threadsafe(started_event.set)
            if block_event is not None:
                block_event.wait()
            return types.SimpleNamespace(
                samples=[0.0] * 100,
                sample_rate=sample_rate,
            )

    return types.SimpleNamespace(
        OfflineTtsKokoroModelConfig=OfflineTtsKokoroModelConfig,
        OfflineTtsModelConfig=OfflineTtsModelConfig,
        OfflineTtsConfig=OfflineTtsConfig,
        OfflineTts=OfflineTts,
    )


# ---- STT reversible unload --------------------------------------------------

@pytest.mark.asyncio
async def test_stt_ensure_loaded_loads_once(tmp_path: Path) -> None:
    d = _stt_dir(tmp_path)
    loads = {"n": 0}

    class Stream:
        def __init__(self) -> None:
            self.result = types.SimpleNamespace(text="hello")

    class Recognizer:
        def create_stream(self) -> Stream:
            return Stream()

        def decode_stream(self, stream: Stream) -> None:  # noqa: ARG002
            pass

    class OfflineRecognizer:
        @staticmethod
        def from_moonshine_v2(*args, **kwargs):  # noqa: ARG004
            loads["n"] += 1
            return Recognizer()

    fake_mod = types.SimpleNamespace(OfflineRecognizer=OfflineRecognizer)
    client = SherpaMoonshineSTT(d, sherpa_module=fake_mod)

    await client.ensure_loaded()
    assert client.loaded

    t1 = asyncio.create_task(client.ensure_loaded())
    t2 = asyncio.create_task(client.ensure_loaded())
    await asyncio.gather(t1, t2)

    assert loads["n"] == 1


@pytest.mark.asyncio
async def test_stt_unload_reloads_and_same_result(tmp_path: Path) -> None:
    d = _stt_dir(tmp_path)
    fake_mod = _fake_stt_module(text="hello world")
    client = SherpaMoonshineSTT(d, sherpa_module=fake_mod)

    wav = _make_wav(16000, [0] * 1000)
    result1 = await client.transcribe(wav, sample_rate=16000, model="moonshine-base-en")

    ref = weakref.ref(client._recognizer)
    assert ref() is not None

    await client.unload()
    assert not client.loaded
    assert ref() is None

    result2 = await client.transcribe(wav, sample_rate=16000, model="moonshine-base-en")
    assert client.loaded
    assert result1.text == result2.text
    assert result1.model == result2.model


@pytest.mark.asyncio
async def test_stt_unload_waits_for_inflight(tmp_path: Path) -> None:
    d = _stt_dir(tmp_path)
    block = threading.Event()
    started = asyncio.Event()
    fake_mod = _fake_stt_module(block_event=block, started_event=started)
    client = SherpaMoonshineSTT(d, sherpa_module=fake_mod)

    wav = _make_wav(16000, [0] * 1000)
    inference = asyncio.create_task(
        client.transcribe(wav, sample_rate=16000, model="moonshine-base-en")
    )

    await started.wait()
    unload_task = asyncio.create_task(client.unload())
    await asyncio.sleep(0)

    assert not unload_task.done()
    block.set()

    await asyncio.gather(inference, unload_task)
    assert not client.loaded


@pytest.mark.asyncio
async def test_stt_inference_while_unload_pending_reloads(tmp_path: Path) -> None:
    d = _stt_dir(tmp_path)
    block = threading.Event()
    started = asyncio.Event()
    fake_mod = _fake_stt_module(text="hello world", block_event=block, started_event=started)
    client = SherpaMoonshineSTT(d, sherpa_module=fake_mod)

    wav = _make_wav(16000, [0] * 1000)
    first = asyncio.create_task(
        client.transcribe(wav, sample_rate=16000, model="moonshine-base-en")
    )

    await started.wait()
    unload_task = asyncio.create_task(client.unload())
    await asyncio.sleep(0)

    second = asyncio.create_task(
        client.transcribe(wav, sample_rate=16000, model="moonshine-base-en")
    )

    block.set()
    r1, _ = await asyncio.gather(first, unload_task)
    r2 = await second

    assert r1.text == "hello world"
    assert r2.text == "hello world"
    assert client.loaded


@pytest.mark.asyncio
async def test_stt_aclose_is_terminal(tmp_path: Path) -> None:
    d = _stt_dir(tmp_path)
    fake_mod = _fake_stt_module()
    client = SherpaMoonshineSTT(d, sherpa_module=fake_mod)

    await client.ensure_loaded()
    assert client.loaded

    await client.aclose()
    assert not client.loaded

    with pytest.raises(RuntimeError, match="closed"):
        await client.ensure_loaded()

    await client.unload()  # no-op, must not raise
    await client.aclose()  # idempotent close


# ---- TTS reversible unload --------------------------------------------------

@pytest.mark.asyncio
async def test_tts_ensure_loaded_loads_once(tmp_path: Path) -> None:
    d = _tts_dir(tmp_path)
    loads = {"n": 0}

    class OfflineTts:
        num_speakers = 10

        def __init__(self, config):  # noqa: ARG002 - matches sherpa's OfflineTts(config)
            loads["n"] += 1

        def generate(self, text, sid, speed):  # noqa: ARG002
            return types.SimpleNamespace(samples=[0.0] * 100, sample_rate=24000)

    class OfflineTtsKokoroModelConfig:
        def __init__(self, **kwargs):  # noqa: ARG002
            pass

    class OfflineTtsModelConfig:
        def __init__(self, *, kokoro, num_threads):  # noqa: ARG002
            pass

    class OfflineTtsConfig:
        def __init__(self, *, model):  # noqa: ARG002
            pass

    fake_mod = types.SimpleNamespace(
        OfflineTtsKokoroModelConfig=OfflineTtsKokoroModelConfig,
        OfflineTtsModelConfig=OfflineTtsModelConfig,
        OfflineTtsConfig=OfflineTtsConfig,
        OfflineTts=OfflineTts,
    )
    client = SherpaKokoroTTS(d, sherpa_module=fake_mod)

    await client.ensure_loaded()
    assert client.loaded

    t1 = asyncio.create_task(client.ensure_loaded())
    t2 = asyncio.create_task(client.ensure_loaded())
    await asyncio.gather(t1, t2)

    assert loads["n"] == 1


@pytest.mark.asyncio
async def test_tts_unload_reloads_and_same_result(tmp_path: Path) -> None:
    d = _tts_dir(tmp_path)
    fake_mod = _fake_tts_module(sample_rate=24000)
    client = SherpaKokoroTTS(d, sherpa_module=fake_mod)

    request = TTSRequest(text="hello world")
    result1 = await client.synthesize(request)

    ref = weakref.ref(client._tts)
    assert ref() is not None

    await client.unload()
    assert not client.loaded
    assert ref() is None

    result2 = await client.synthesize(request)
    assert client.loaded
    assert result1.bytes_produced == result2.bytes_produced
    assert result1.content_type == result2.content_type


@pytest.mark.asyncio
async def test_tts_unload_waits_for_inflight(tmp_path: Path) -> None:
    d = _tts_dir(tmp_path)
    block = threading.Event()
    started = asyncio.Event()
    fake_mod = _fake_tts_module(block_event=block, started_event=started)
    client = SherpaKokoroTTS(d, sherpa_module=fake_mod)

    inference = asyncio.create_task(client.synthesize(TTSRequest(text="hello")))
    await started.wait()

    unload_task = asyncio.create_task(client.unload())
    await asyncio.sleep(0)

    assert not unload_task.done()
    block.set()

    await asyncio.gather(inference, unload_task)
    assert not client.loaded


@pytest.mark.asyncio
async def test_tts_inference_while_unload_pending_reloads(tmp_path: Path) -> None:
    d = _tts_dir(tmp_path)
    block = threading.Event()
    started = asyncio.Event()
    fake_mod = _fake_tts_module(block_event=block, started_event=started, sample_rate=24000)
    client = SherpaKokoroTTS(d, sherpa_module=fake_mod)

    first = asyncio.create_task(client.synthesize(TTSRequest(text="hello world")))
    await started.wait()

    unload_task = asyncio.create_task(client.unload())
    await asyncio.sleep(0)

    second = asyncio.create_task(client.synthesize(TTSRequest(text="hello world")))
    block.set()

    r1, _ = await asyncio.gather(first, unload_task)
    r2 = await second

    assert r1.bytes_produced > 0
    assert r2.bytes_produced == r1.bytes_produced
    assert client.loaded


@pytest.mark.asyncio
async def test_tts_aclose_is_terminal(tmp_path: Path) -> None:
    d = _tts_dir(tmp_path)
    fake_mod = _fake_tts_module()
    client = SherpaKokoroTTS(d, sherpa_module=fake_mod)

    await client.ensure_loaded()
    assert client.loaded

    await client.aclose()
    assert not client.loaded

    with pytest.raises(RuntimeError, match="closed"):
        await client.ensure_loaded()

    await client.unload()  # no-op
    await client.aclose()  # idempotent
