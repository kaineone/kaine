# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the Qwen3-TTS vocal backend using injected fakes."""
from __future__ import annotations

import types
from typing import Any

import numpy as np
import pytest

from kaine.modules.vocal.client import SynthesisResult, TTSClient, TTSRequest
from kaine.modules.vocal.qwen3_tts import APPLIED_PROSODY, Qwen3TTS


def _fake_qwen_tts_module(
    *,
    speakers: list[str] | None = None,
    sample_rate: int = 24000,
    duration_samples: int = 480,
) -> types.ModuleType:
    """Build a fake qwen_tts module whose model returns deterministic audio."""
    if speakers is None:
        speakers = ["Ryan", "Allison", "Zara"]
    generated_calls: list[dict[str, Any]] = []

    class FakeTokenizer:
        @classmethod
        def from_pretrained(cls, *args: Any, **kwargs: Any) -> "FakeTokenizer":
            return cls()

    class FakeModel:
        @classmethod
        def from_pretrained(cls, *args: Any, **kwargs: Any) -> "FakeModel":
            return cls()

        def get_supported_speakers(self) -> list[str]:
            return list(speakers)

        def generate_custom_voice(
            self,
            text: str = "",
            language: str = "English",
            speaker: str = "",
            instruct: str = "",
            **kwargs: Any,
        ) -> tuple[list[np.ndarray], int]:
            generated_calls.append(
                {
                    "text": text,
                    "language": language,
                    "speaker": speaker,
                    "instruct": instruct,
                }
            )
            samples = np.sin(
                np.linspace(0, 2 * np.pi * 440, duration_samples, dtype=np.float32)
            )
            return [samples], sample_rate

    mod = types.ModuleType("qwen_tts")
    mod.Qwen3TTSModel = FakeModel  # type: ignore[attr-defined]
    mod.Qwen3TTSTokenizer = FakeTokenizer  # type: ignore[attr-defined]
    mod._generated_calls = generated_calls  # type: ignore[attr-defined]
    return mod


@pytest.fixture
def fake_module() -> types.ModuleType:
    return _fake_qwen_tts_module()


def _make_client(fake_module: types.ModuleType, **kwargs: Any) -> Qwen3TTS:
    return Qwen3TTS(_qwen_tts_module=fake_module, **kwargs)


class TestConstruction:
    def test_base_url_uses_short_name(self, fake_module: types.ModuleType) -> None:
        client = _make_client(fake_module)
        assert client.base_url == "qwen3-tts://Qwen3-TTS-Sam-0.6B"

    def test_not_loaded_initially(self, fake_module: types.ModuleType) -> None:
        client = _make_client(fake_module)
        assert not client.loaded


class TestProtocol:
    def test_satisfies_tts_client_protocol(self, fake_module: types.ModuleType) -> None:
        client = _make_client(fake_module)
        assert isinstance(client, TTSClient)


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_warm_up_loads_model(self, fake_module: types.ModuleType) -> None:
        client = _make_client(fake_module)
        try:
            await client.warm_up()
            assert client.loaded
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_unload_frees_model(self, fake_module: types.ModuleType) -> None:
        client = _make_client(fake_module)
        try:
            await client.warm_up()
            assert client.loaded
            await client.unload()
            assert not client.loaded
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_reload_after_unload(self, fake_module: types.ModuleType) -> None:
        client = _make_client(fake_module)
        try:
            await client.warm_up()
            await client.unload()
            assert not client.loaded
            await client.ensure_loaded()
            assert client.loaded
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_close_sets_closed(self, fake_module: types.ModuleType) -> None:
        client = _make_client(fake_module)
        await client.aclose()
        assert not client.loaded

    @pytest.mark.asyncio
    async def test_synthesize_after_close_raises(
        self, fake_module: types.ModuleType,
    ) -> None:
        client = _make_client(fake_module)
        await client.aclose()
        with pytest.raises(RuntimeError, match="closed"):
            await client.synthesize(TTSRequest(text="hello"))


class TestSynthesis:
    @pytest.mark.asyncio
    async def test_basic_synthesis(self, fake_module: types.ModuleType) -> None:
        client = _make_client(fake_module)
        try:
            result = await client.synthesize(TTSRequest(text="hello world"))
            assert isinstance(result, SynthesisResult)
            assert result.content_type == "audio/wav"
            assert result.output_format == "wav"
            assert result.bytes_produced > 0
            assert result.latency_ms >= 0.0
            assert result.audio[:4] == b"RIFF"
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_passes_language(self, fake_module: types.ModuleType) -> None:
        client = _make_client(fake_module)
        try:
            await client.synthesize(
                TTSRequest(text="bonjour", language="French")
            )
            calls = fake_module._generated_calls  # type: ignore[attr-defined]
            assert calls[-1]["language"] == "French"
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_passes_instruct(self, fake_module: types.ModuleType) -> None:
        client = _make_client(fake_module)
        try:
            await client.synthesize(
                TTSRequest(text="I am happy", instruct="Speak with warm enthusiasm")
            )
            calls = fake_module._generated_calls  # type: ignore[attr-defined]
            assert calls[-1]["instruct"] == "Speak with warm enthusiasm"
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_default_language_is_english(
        self, fake_module: types.ModuleType,
    ) -> None:
        client = _make_client(fake_module)
        try:
            await client.synthesize(TTSRequest(text="hello"))
            calls = fake_module._generated_calls  # type: ignore[attr-defined]
            assert calls[-1]["language"] == "English"
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_empty_text_raises(self, fake_module: types.ModuleType) -> None:
        client = _make_client(fake_module)
        try:
            with pytest.raises(ValueError, match="empty"):
                await client.synthesize(TTSRequest(text=""))
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_whitespace_text_raises(self, fake_module: types.ModuleType) -> None:
        client = _make_client(fake_module)
        try:
            with pytest.raises(ValueError, match="empty"):
                await client.synthesize(TTSRequest(text="   "))
        finally:
            await client.aclose()


class TestSpeakerResolution:
    @pytest.mark.asyncio
    async def test_default_speaker_is_sam(
        self, fake_module: types.ModuleType,
    ) -> None:
        client = _make_client(fake_module)
        try:
            await client.synthesize(TTSRequest(text="hi"))
            calls = fake_module._generated_calls  # type: ignore[attr-defined]
            assert calls[-1]["speaker"] == "sam"
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_empty_speaker_picks_first_alphabetically(
        self, fake_module: types.ModuleType,
    ) -> None:
        client = _make_client(fake_module, speaker="")
        try:
            await client.synthesize(TTSRequest(text="hi"))
            calls = fake_module._generated_calls  # type: ignore[attr-defined]
            assert calls[-1]["speaker"] == "Allison"
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_explicit_speaker(self, fake_module: types.ModuleType) -> None:
        client = _make_client(fake_module, speaker="Zara")
        try:
            await client.synthesize(TTSRequest(text="hi"))
            calls = fake_module._generated_calls  # type: ignore[attr-defined]
            assert calls[-1]["speaker"] == "Zara"
        finally:
            await client.aclose()


class TestAppliedProsody:
    def test_applied_prosody_tuple(self) -> None:
        assert APPLIED_PROSODY == ("instruct", "language")
