# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from kaine.residency.speech_rungs import (
    LADDERS,
    STT_LADDER,
    TTS_LADDER,
    SpeechRung,
    is_rung_installed,
    lookup_footprint,
    rung_key,
)


def test_tts_ladder_order():
    assert len(TTS_LADDER) == 2
    assert TTS_LADDER[0].backend == "chatterbox"
    assert TTS_LADDER[1].backend == "sherpa_onnx"
    assert TTS_LADDER[1].model_id == "kokoro-en"


def test_stt_ladder_order():
    assert len(STT_LADDER) == 3
    assert STT_LADDER[0].backend == "speaches"
    assert STT_LADDER[1].model_id == "moonshine-base-en"
    assert STT_LADDER[2].model_id == "moonshine-tiny-en"


def test_ladders_keys():
    assert set(LADDERS.keys()) == {"vocal.tts", "audition.stt"}
    assert LADDERS["vocal.tts"] is TTS_LADDER
    assert LADDERS["audition.stt"] is STT_LADDER


def test_rung_key():
    assert rung_key(TTS_LADDER[0]) == "chatterbox:chatterbox"
    assert rung_key(STT_LADDER[1]) == "sherpa_onnx:moonshine-base-en"


def test_lookup_footprint_match():
    """lookup_footprint returns the max bytes when entries match."""
    from types import SimpleNamespace

    entries = [
        SimpleNamespace(
            component="vocal.tts",
            backend="sherpa_onnx",
            model_id="kokoro-en",
            host_class="cpu",
            bytes=200_000_000,
        ),
        SimpleNamespace(
            component="vocal.tts",
            backend="sherpa_onnx",
            model_id="kokoro-en",
            host_class="cpu",
            bytes=250_000_000,
        ),
    ]
    result = lookup_footprint(TTS_LADDER[1], "vocal.tts", entries, "cpu")
    assert result == 250_000_000


def test_lookup_footprint_no_match():
    result = lookup_footprint(TTS_LADDER[0], "vocal.tts", [], "cpu")
    assert result is None


def test_is_rung_installed_service_backends(monkeypatch):
    """Service backends (chatterbox, speaches) are always installed."""
    assert is_rung_installed(TTS_LADDER[0]) is True
    assert is_rung_installed(STT_LADDER[0]) is True


def test_is_rung_installed_sherpa_delegates(monkeypatch):
    """sherpa_onnx rung delegates to speech_manifest.is_installed."""
    monkeypatch.setattr("kaine.speech_manifest.is_installed", lambda mid: mid == "kokoro-en")
    assert is_rung_installed(TTS_LADDER[1]) is True
    assert is_rung_installed(STT_LADDER[1]) is False


def test_speech_rung_frozen():
    import dataclasses

    assert dataclasses.is_dataclass(TTS_LADDER[0])
    import pytest

    with pytest.raises(dataclasses.FrozenInstanceError):
        TTS_LADDER[0].backend = "other"  # type: ignore[misc]


def test_quantization_field():
    assert TTS_LADDER[0].quantization is None
    assert TTS_LADDER[1].quantization == "int8"
    for rung in STT_LADDER:
        assert rung.quantization is None or isinstance(rung.quantization, str)


def test_weights_sha256_field():
    for ladder in LADDERS.values():
        for rung in ladder:
            assert rung.weights_sha256 is None or isinstance(rung.weights_sha256, str)


def test_quantization_roundtrip():
    rung = SpeechRung(
        backend="sherpa_onnx",
        model_id="test",
        label="test",
        licence="MIT",
        mapped=False,
        fetch_command="",
        quantization="Q4_K_M",
        weights_sha256="abc123",
    )
    assert rung.quantization == "Q4_K_M"
    assert rung.weights_sha256 == "abc123"
