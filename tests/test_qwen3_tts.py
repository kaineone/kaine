# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import io
import sys
import types
import wave

import numpy as np
import pytest

from kaine.modules.affect.state import DimensionalState
from kaine.modules.vocal.client import TTSClient, TTSRequest
from kaine.modules.vocal.mapping import affect_to_instruct


class _FakeModel:
    calls: list[dict] = []

    def get_supported_speakers(self):
        return ["Ryan", "Aiden"]

    def generate_custom_voice(self, text, language, speaker, instruct):
        _FakeModel.calls.append(
            {"text": text, "language": language, "speaker": speaker, "instruct": instruct}
        )
        return [np.full(2400, 0.25, dtype=np.float32)], 24000


@pytest.fixture
def fake_qwen(monkeypatch):
    _FakeModel.calls = []
    loads: list[tuple] = []

    class _Qwen3TTSModel:
        @staticmethod
        def from_pretrained(model_id, device_map=None, torch_dtype=None):
            loads.append((model_id, device_map, torch_dtype))
            return _FakeModel()

    qwen_mod = types.ModuleType("qwen_tts")
    qwen_mod.Qwen3TTSModel = _Qwen3TTSModel
    torch_mod = types.ModuleType("torch")
    torch_mod.bfloat16 = "bf16-sentinel"
    torch_mod.cuda = types.SimpleNamespace(is_available=lambda: False)
    monkeypatch.setitem(sys.modules, "qwen_tts", qwen_mod)
    monkeypatch.setitem(sys.modules, "torch", torch_mod)
    return loads


def _make():
    from kaine.modules.vocal.qwen3_tts import Qwen3TTS

    return Qwen3TTS(device="cpu")


def test_protocol_and_base_url():
    client = _make()
    assert isinstance(client, TTSClient)
    assert client.base_url == "local://qwen3-tts"


@pytest.mark.asyncio
async def test_synthesize_encodes_wav_and_passes_instruct(fake_qwen):
    client = _make()
    result = await client.synthesize(
        TTSRequest(text="hello", language="English", instruct="Speak with quiet sadness")
    )
    await client.aclose()
    assert fake_qwen == [("Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice", "cpu", "bf16-sentinel")]
    assert _FakeModel.calls == [
        {
            "text": "hello",
            "language": "English",
            "speaker": "Ryan",
            "instruct": "Speak with quiet sadness",
        }
    ]
    assert result.content_type == "audio/wav"
    assert result.bytes_produced == len(result.audio)
    with wave.open(io.BytesIO(result.audio), "rb") as wf:
        assert wf.getframerate() == 24000
        assert wf.getnchannels() == 1
        assert wf.getnframes() == 2400


@pytest.mark.asyncio
async def test_speed_factor_shortens_audio(fake_qwen):
    client = _make()
    result = await client.synthesize(TTSRequest(text="hi", speed_factor=2.0))
    await client.aclose()
    with wave.open(io.BytesIO(result.audio), "rb") as wf:
        assert wf.getnframes() == 1200
    assert _FakeModel.calls[0]["language"] == "Auto"
    assert _FakeModel.calls[0]["instruct"] is None


@pytest.mark.asyncio
async def test_empty_text_rejected_and_ticket_released(fake_qwen):
    client = _make()
    with pytest.raises(ValueError):
        await client.synthesize(TTSRequest(text="  "))
    await client.unload()
    assert client.loaded is False
    await client.aclose()


@pytest.mark.asyncio
async def test_unload_ensure_loaded_cycle(fake_qwen):
    client = _make()
    assert client.loaded is False
    await client.ensure_loaded()
    assert client.loaded is True
    await client.ensure_loaded()
    assert len(fake_qwen) == 1
    await client.unload()
    assert client.loaded is False
    await client.unload()
    await client.synthesize(TTSRequest(text="again"))
    assert client.loaded is True
    assert len(fake_qwen) == 2
    await client.aclose()
    with pytest.raises(RuntimeError):
        await client.ensure_loaded()


@pytest.mark.parametrize(
    "valence,arousal,expected",
    [
        (0.8, 0.9, "Speak with enthusiastic joy"),
        (0.8, 0.1, "Speak with gentle warmth and contentment"),
        (-0.8, 0.9, "Speak with urgent concern"),
        (-0.8, 0.1, "Speak with quiet sadness"),
        (0.0, 0.3, ""),
        (0.1, 0.9, ""),
    ],
)
def test_affect_to_instruct(valence, arousal, expected):
    state = DimensionalState(valence=valence, arousal=arousal, dominance=0.0)
    assert affect_to_instruct(state) == expected
