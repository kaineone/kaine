# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the sherpa-onnx speech health probes and dependency specs."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import kaine.setup.speech_models as _speech_models_mod
from kaine.nexus.health.config import build_dependency_specs
from kaine.nexus.health.probes import (
    DEGRADED,
    DOWN,
    UP,
    clear_sherpa_probe_memo,
    probe_sherpa_stt,
    probe_sherpa_tts,
)


class _FakeSTTResult:
    def __init__(self, text: str = "") -> None:
        self.text = text


class _FakeTTSResult:
    def __init__(self, audio: bytes) -> None:
        self.audio = audio


class _FakeSherpaSTT:
    _raise: BaseException | None = None
    constructions: int = 0

    def __init__(self, model_dir: str, *, model_id, num_threads) -> None:
        type(self).constructions += 1
        if self._raise is not None:
            raise self._raise

    async def transcribe(self, audio_bytes, *, sample_rate, model, filename):
        return _FakeSTTResult("")

    async def aclose(self):
        pass


class _FakeSherpaTTS:
    _raise: BaseException | None = None
    _audio: bytes = b""
    constructions: int = 0

    def __init__(self, model_dir: str, *, model_id, speaker_id, num_threads) -> None:
        type(self).constructions += 1
        if self._raise is not None:
            raise self._raise

    async def synthesize(self, req):
        return _FakeTTSResult(self._audio)

    async def aclose(self):
        pass


@pytest.fixture
def _patch_speech_models(monkeypatch):
    monkeypatch.setattr(_speech_models_mod, "DEFAULT_STT", "moonshine-base-en")
    monkeypatch.setattr(_speech_models_mod, "DEFAULT_TTS", "kokoro-en")
    monkeypatch.setattr(
        _speech_models_mod, "model_dir", lambda model_id: Path(f"/fake/models/{model_id}")
    )


@pytest.fixture(autouse=True)
def _clear_sherpa_memo():
    clear_sherpa_probe_memo()
    _FakeSherpaSTT.constructions = 0
    _FakeSherpaTTS.constructions = 0
    _FakeSherpaSTT._raise = None
    _FakeSherpaTTS._raise = None
    yield
    clear_sherpa_probe_memo()


@pytest.fixture
def _patch_engines(monkeypatch, _patch_speech_models):
    monkeypatch.setattr(
        "kaine.modules.audition.sherpa_stt.SherpaMoonshineSTT", _FakeSherpaSTT
    )
    monkeypatch.setattr(
        "kaine.modules.vox.sherpa_tts.SherpaKokoroTTS", _FakeSherpaTTS
    )


def _specs(audition_cfg=None, vox_cfg=None):
    return build_dependency_specs(
        redis_cfg={"host": "127.0.0.1", "port": 6379},
        qdrant_cfg={},
        qdrant_secret_key=None,
        redis_password=None,
        lingua_cfg={},
        audition_cfg=audition_cfg or {},
        vox_cfg=vox_cfg or {},
        nous_cfg={},
        state_encryption_cfg=None,
    )


def _spec_named(specs, name):
    matches = [s for s in specs if s.name == name]
    assert len(matches) == 1
    return matches[0]


def test_probe_sherpa_stt_up_when_fake_transcribes(_patch_engines):
    status, detail = asyncio.run(
        probe_sherpa_stt(model_dir="/fake/stt", model_id="moonshine-base-en", num_threads=2)
    )
    assert status == UP
    assert "loaded and transcribed a test clip" in detail


def test_probe_sherpa_stt_down_on_constructor_error(_patch_engines):
    _FakeSherpaSTT._raise = FileNotFoundError("missing encoder_model.ort")
    try:
        status, detail = asyncio.run(
            probe_sherpa_stt(
                model_dir="/fake/stt", model_id="moonshine-base-en", num_threads=2
            )
        )
        assert status == DOWN
        assert "FileNotFoundError" in detail
        assert "missing encoder_model.ort" in detail
    finally:
        _FakeSherpaSTT._raise = None


def test_probe_sherpa_tts_up_when_fake_synthesizes(_patch_engines):
    _FakeSherpaTTS._audio = b"RIFF....WAVE"
    try:
        status, detail = asyncio.run(
            probe_sherpa_tts(
                model_dir="/fake/tts",
                model_id="kokoro-en",
                speaker_id=0,
                num_threads=2,
            )
        )
        assert status == UP
        assert "loaded and synthesized a test word" in detail
    finally:
        _FakeSherpaTTS._audio = b""


def test_probe_sherpa_tts_down_on_constructor_error(_patch_engines):
    _FakeSherpaTTS._raise = FileNotFoundError("missing model.int8.onnx")
    try:
        status, detail = asyncio.run(
            probe_sherpa_tts(
                model_dir="/fake/tts",
                model_id="kokoro-en",
                speaker_id=0,
                num_threads=2,
            )
        )
        assert status == DOWN
        assert "FileNotFoundError" in detail
        assert "missing model.int8.onnx" in detail
    finally:
        _FakeSherpaTTS._raise = None


def test_probe_sherpa_tts_down_on_empty_audio(_patch_engines):
    _FakeSherpaTTS._audio = b""
    status, detail = asyncio.run(
        probe_sherpa_tts(
            model_dir="/fake/tts",
            model_id="kokoro-en",
            speaker_id=0,
            num_threads=2,
        )
    )
    assert status == DOWN
    assert "empty" in detail.lower()


def test_probe_sherpa_stt_memo_reuses_up_result(_patch_engines):
    _FakeSherpaSTT.constructions = 0
    status, detail = asyncio.run(
        probe_sherpa_stt(model_dir="/fake/stt", model_id="moonshine-base-en", num_threads=2)
    )
    assert status == UP
    first_constructions = _FakeSherpaSTT.constructions
    status, detail = asyncio.run(
        probe_sherpa_stt(model_dir="/fake/stt", model_id="moonshine-base-en", num_threads=2)
    )
    assert status == UP
    assert _FakeSherpaSTT.constructions == first_constructions
    assert "verified" in detail


def test_probe_sherpa_stt_memo_reuses_down_result(_patch_engines):
    _FakeSherpaSTT._raise = FileNotFoundError("missing encoder_model.ort")
    _FakeSherpaSTT.constructions = 0
    try:
        status, detail = asyncio.run(
            probe_sherpa_stt(model_dir="/fake/stt", model_id="moonshine-base-en", num_threads=2)
        )
        assert status == DOWN
        first_constructions = _FakeSherpaSTT.constructions
        status, detail = asyncio.run(
            probe_sherpa_stt(model_dir="/fake/stt", model_id="moonshine-base-en", num_threads=2)
        )
        assert status == DOWN
        assert _FakeSherpaSTT.constructions == first_constructions
        assert "retry in" in detail
    finally:
        _FakeSherpaSTT._raise = None


def test_probe_sherpa_stt_memo_retries_after_window(_patch_engines, monkeypatch):
    import kaine.nexus.health.probes as probes_mod

    class _FakeTime:
        def __init__(self, now: float) -> None:
            self.now = now

        def monotonic(self) -> float:
            return self.now

    fake_time = _FakeTime(1000.0)
    monkeypatch.setattr(probes_mod, "time", fake_time)
    _FakeSherpaSTT._raise = FileNotFoundError("missing encoder_model.ort")
    _FakeSherpaSTT.constructions = 0
    try:
        status, detail = asyncio.run(
            probe_sherpa_stt(model_dir="/fake/stt", model_id="moonshine-base-en", num_threads=2)
        )
        assert status == DOWN
        first_constructions = _FakeSherpaSTT.constructions
        fake_time.now += 61.0
        status, detail = asyncio.run(
            probe_sherpa_stt(model_dir="/fake/stt", model_id="moonshine-base-en", num_threads=2)
        )
        assert status == DOWN
        assert _FakeSherpaSTT.constructions == first_constructions + 1
    finally:
        _FakeSherpaSTT._raise = None


def test_dependency_specs_sherpa_onnx_audition_row(_patch_speech_models):
    specs = _specs(
        audition_cfg={"backend": "sherpa_onnx", "transcription_enabled": True}
    )
    names = {s.name for s in specs}
    assert "sherpa-onnx (Moonshine)" in names
    assert "Speaches (STT)" not in names


def test_dependency_specs_default_audition_row(_patch_speech_models):
    specs = _specs()
    names = {s.name for s in specs}
    assert "Speaches (STT)" in names
    assert "sherpa-onnx (Moonshine)" not in names


def test_dependency_specs_sherpa_onnx_vox_row(_patch_speech_models):
    specs = _specs(vox_cfg={"backend": "sherpa_onnx"})
    names = {s.name for s in specs}
    assert "sherpa-onnx (Kokoro)" in names
    assert "Chatterbox (TTS)" not in names


def test_dependency_specs_default_vox_row(_patch_speech_models):
    specs = _specs()
    names = {s.name for s in specs}
    assert "Chatterbox (TTS)" in names
    assert "sherpa-onnx (Kokoro)" not in names


def test_dependency_specs_unknown_audition_backend(_patch_speech_models):
    specs = _specs(audition_cfg={"backend": "whisper"})
    row = _spec_named(specs, "Audition backend 'whisper'")
    status, detail = asyncio.run(row.probe())
    assert status == DEGRADED
    assert "unknown [audition].backend" in detail


def test_dependency_specs_unknown_vox_backend(_patch_speech_models):
    specs = _specs(vox_cfg={"backend": "whisper"})
    row = _spec_named(specs, "Vox backend 'whisper'")
    status, detail = asyncio.run(row.probe())
    assert status == DEGRADED
    assert "unknown [vox].backend" in detail


def test_tier1_profile_uses_sherpa_onnx_speech():
    import tomllib

    profile = Path("config/profiles/tier1.toml").read_text(encoding="utf-8")
    data = tomllib.loads(profile)
    assert data["tier"]["unsupported_modules"] == []
    assert data["audition"]["backend"] == "sherpa_onnx"
    assert data["vox"]["backend"] == "sherpa_onnx"
    assert not any(".wav" in str(v) for v in _all_string_values(data))


def _all_string_values(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _all_string_values(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _all_string_values(item)
