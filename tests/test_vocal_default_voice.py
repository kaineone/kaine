# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import dataclasses
import json
import logging
import pathlib
import tomllib

import httpx
import pytest

from kaine.backend_state import backend_failures, clear_backend_failures
from kaine.boot import ConfigurationError, make_vocal
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.config import load_kaine_config
from kaine.modules.vocal import FakePlayer, Vocal
from kaine.modules.vocal.client import ChatterboxClient


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


@pytest.fixture(autouse=True)
def _clean_backend_state():
    clear_backend_failures()
    yield
    clear_backend_failures()


def _fake_chatterbox_server(voice_payload, *, unreachable=False):
    recorded = []

    def _json_body(request: httpx.Request):
        if not request.content:
            return None
        try:
            return json.loads(request.content.decode("utf-8"))
        except Exception:
            return None

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append((request.method, request.url.path, _json_body(request)))
        if request.method == "GET" and request.url.path == "/get_predefined_voices":
            if unreachable:
                raise httpx.ConnectError("cannot reach fake-chatterbox")
            return httpx.Response(200, json=voice_payload)
        if request.method == "POST" and request.url.path == "/tts":
            return httpx.Response(
                200,
                content=b"FAKE_WAV_DATA",
                headers={"content-type": "audio/wav"},
            )
        return httpx.Response(404)

    client = ChatterboxClient(
        base_url="http://fake-chatterbox",
        transport=httpx.MockTransport(handler),
    )
    return client, recorded


async def _open_vocal(bus, client, tmp_path, **kw):
    vocal = Vocal(
        bus,
        tts_client=client,
        player=FakePlayer(),
        sink_path=tmp_path / "vox",
        **kw,
    )
    await vocal.initialize()
    return vocal


def _last_payload(entries):
    assert entries
    fields = entries[-1][1]
    raw = fields.get("payload") or fields.get(b"payload")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)


@pytest.mark.asyncio
async def test_chatterbox_picks_first_sorted_voice(bus, tmp_path):
    voices = [
        {"display_name": "Olivia", "filename": "Olivia.wav"},
        {"display_name": "Abigail", "filename": "abigail.wav"},
        {"display_name": "Henry", "filename": "Henry.wav"},
    ]
    client, requests = _fake_chatterbox_server(voices)
    vocal = await _open_vocal(bus, client, tmp_path)
    try:
        assert vocal.voice_id == "abigail.wav"
        result = await vocal.synthesize_text("hello")
        assert result.bytes_produced > 0
        tts = next(r for r in requests if r[0] == "POST" and r[1] == "/tts")
        assert tts[2]["predefined_voice_id"] == "abigail.wav"
    finally:
        await vocal.shutdown()


@pytest.mark.asyncio
async def test_chatterbox_pick_is_deterministic(bus, tmp_path):
    voices_a = [
        {"display_name": "Olivia", "filename": "Olivia.wav"},
        {"display_name": "Abigail", "filename": "abigail.wav"},
        {"display_name": "Henry", "filename": "Henry.wav"},
    ]
    voices_b = list(reversed(voices_a))
    client_a, _ = _fake_chatterbox_server(voices_a)
    client_b, _ = _fake_chatterbox_server(voices_b)
    vocal_a = await _open_vocal(bus, client_a, tmp_path)
    try:
        vocal_b = await _open_vocal(bus, client_b, tmp_path)
        try:
            assert vocal_a.voice_id == "abigail.wav"
            assert vocal_b.voice_id == "abigail.wav"
        finally:
            await vocal_b.shutdown()
    finally:
        await vocal_a.shutdown()


@pytest.mark.asyncio
async def test_chatterbox_logs_choice_once(bus, tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="kaine.modules.vocal.module")
    voices = [
        {"display_name": "Abigail", "filename": "abigail.wav"},
        {"display_name": "Henry", "filename": "Henry.wav"},
    ]
    client, _ = _fake_chatterbox_server(voices)
    vocal = await _open_vocal(bus, client, tmp_path)
    try:
        hits = [
            r
            for r in caplog.records
            if "vocal module voice:" in r.message and "abigail.wav" in r.message
        ]
        assert len(hits) == 1
    finally:
        await vocal.shutdown()


@pytest.mark.asyncio
async def test_chatterbox_gender_not_knowable(bus, tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="kaine.modules.vocal.module")
    voices = [
        {"display_name": "Abigail", "filename": "abigail.wav"},
        {"display_name": "Henry", "filename": "Henry.wav"},
    ]
    client, _ = _fake_chatterbox_server(voices)
    vocal = await _open_vocal(bus, client, tmp_path, voice_gender="male")
    try:
        assert vocal.voice_id == "abigail.wav"
        assert any("reports no gender" in r.message for r in caplog.records)
    finally:
        await vocal.shutdown()


@pytest.mark.asyncio
async def test_configured_voice_wins_without_query(bus, tmp_path):
    client, requests = _fake_chatterbox_server([])
    vocal = await _open_vocal(bus, client, tmp_path, predefined_voice_id="mine.wav")
    try:
        assert vocal.voice_id == "mine.wav"
        assert not any(r[0] == "GET" and r[1] == "/get_predefined_voices" for r in requests)
        await vocal.synthesize_text("hello")
        tts = next(r for r in requests if r[0] == "POST" and r[1] == "/tts")
        assert tts[2]["predefined_voice_id"] == "mine.wav"
    finally:
        await vocal.shutdown()


@pytest.mark.asyncio
async def test_default_voice_wins(bus, tmp_path):
    voices = [
        {"display_name": "Abigail", "filename": "abigail.wav"},
        {"display_name": "Henry", "filename": "Henry.wav"},
    ]
    client, _ = _fake_chatterbox_server(voices)
    vocal = await _open_vocal(bus, client, tmp_path, default_voice="henry")
    try:
        assert vocal.voice_id == "Henry.wav"
    finally:
        await vocal.shutdown()


@pytest.mark.asyncio
async def test_unreachable_server_degrades(bus, tmp_path, caplog):
    caplog.set_level(logging.WARNING, logger="kaine.modules.vocal.module")
    client, requests = _fake_chatterbox_server([], unreachable=True)
    vocal = await _open_vocal(bus, client, tmp_path)
    try:
        assert "cannot list the voices" in vocal._tts_unavailable
        failures = backend_failures()
        assert any(
            f.module == "vocal"
            and f.backend == "chatterbox"
            and "cannot list the voices" in f.reason
            for f in failures
        )
        assert any(r.message.startswith("vocal module silent:") for r in caplog.records)

        result = await vocal.synthesize_text("hello")
        assert result.bytes_produced == 0
        assert vocal._player.played == []
        assert not any(r[0] == "POST" and r[1] == "/tts" for r in requests)

        entries = await bus.client.xrange("vocal.out", "-", "+")
        event = _last_payload(entries)
        assert event["success"] is False
        assert "no voice" in event["error"]
    finally:
        await vocal.shutdown()


@pytest.mark.asyncio
async def test_empty_list_degrades(bus, tmp_path, caplog):
    caplog.set_level(logging.WARNING, logger="kaine.modules.vocal.module")
    client, requests = _fake_chatterbox_server([])
    vocal = await _open_vocal(bus, client, tmp_path)
    try:
        assert vocal._tts_unavailable is not None
        assert any("[vocal].predefined_voice_id" in r.message for r in caplog.records)
        assert not any(r[0] == "POST" and r[1] == "/tts" for r in requests)
        result = await vocal.synthesize_text("hello")
        assert result.bytes_produced == 0
    finally:
        await vocal.shutdown()


@pytest.mark.asyncio
async def test_unknown_default_voice_degrades(bus, tmp_path, caplog):
    caplog.set_level(logging.WARNING, logger="kaine.modules.vocal.module")
    voices = [
        {"display_name": "Abigail", "filename": "abigail.wav"},
    ]
    client, requests = _fake_chatterbox_server(voices)
    vocal = await _open_vocal(bus, client, tmp_path, default_voice="nobody.wav")
    try:
        assert vocal._tts_unavailable is not None
        failures = backend_failures()
        assert any(
            f.module == "vocal"
            and f.backend == "chatterbox"
            and "[vocal].default_voice" in f.reason
            for f in failures
        )
        assert not any(r[0] == "POST" and r[1] == "/tts" for r in requests)
    finally:
        await vocal.shutdown()


@pytest.mark.asyncio
async def test_invalid_gender_rejected(bus):
    with pytest.raises(ValueError, match="voice_gender"):
        Vocal(bus, voice_gender="robot")
    with pytest.raises(ConfigurationError, match="voice_gender"):
        make_vocal(bus, {"voice_gender": "robot"})


@pytest.mark.asyncio
async def test_kokoro_fake_speaker_table(bus, monkeypatch):
    from kaine import speech_manifest

    captured: list[int] = []

    class FakeSherpa:
        def __init__(self, model_dir, *, model_id, speaker_id, num_threads):
            captured.append(speaker_id)

    monkeypatch.setattr(
        "kaine.modules.vocal.sherpa_tts.SherpaKokoroTTS", FakeSherpa
    )
    monkeypatch.setattr(
        "kaine.model_paths.speech_model_dir", lambda _id: f"/fake/models/{_id}"
    )
    monkeypatch.setattr("kaine.model_paths.DEFAULT_TTS", "kokoro-en")

    original = speech_manifest.MANIFEST["kokoro-en"]
    monkeypatch.setitem(
        speech_manifest.MANIFEST,
        "kokoro-en",
        dataclasses.replace(original, speakers=("bm_george", "af_sky", "am_adam", "af")),
    )

    for gender, expected_id in (("any", 3), ("female", 3), ("male", 2)):
        captured.clear()
        vocal = make_vocal(bus, {"backend": "sherpa_onnx", "voice_gender": gender})
        assert captured == [expected_id]
        assert vocal._voice_label == f"kokoro-en speaker {expected_id}"

    captured.clear()
    vocal = make_vocal(bus, {"backend": "sherpa_onnx", "default_voice": "bm_george"})
    assert captured == [0]
    assert vocal._voice_label == "kokoro-en speaker 0"

    captured.clear()
    vocal = make_vocal(
        bus,
        {
            "backend": "sherpa_onnx",
            "voice_gender": "male",
            "default_voice": "bm_george",
            "sherpa_speaker_id": 1,
        },
    )
    assert captured == [1]
    assert vocal._voice_label == "kokoro-en speaker 1"

    monkeypatch.setitem(
        speech_manifest.MANIFEST,
        "kokoro-en",
        dataclasses.replace(original, speakers=("af", "bf_emma")),
    )
    vocal = make_vocal(bus, {"backend": "sherpa_onnx", "voice_gender": "male"})
    assert vocal is None
    failures = backend_failures()
    assert any(
        f.module == "vocal"
        and f.backend == "sherpa_onnx"
        and "voice_gender" in f.reason
        for f in failures
    )


@pytest.mark.asyncio
async def test_kokoro_real_table_default_is_speaker_zero(bus, monkeypatch):
    captured: list[int] = []

    class FakeSherpa:
        def __init__(self, model_dir, *, model_id, speaker_id, num_threads):
            captured.append(speaker_id)

    monkeypatch.setattr(
        "kaine.modules.vocal.sherpa_tts.SherpaKokoroTTS", FakeSherpa
    )
    monkeypatch.setattr(
        "kaine.model_paths.speech_model_dir", lambda _id: f"/fake/models/{_id}"
    )
    monkeypatch.setattr("kaine.model_paths.DEFAULT_TTS", "kokoro-en")

    vocal = make_vocal(bus, {"backend": "sherpa_onnx"})
    assert captured == [0]
    assert vocal._voice_label == "kokoro-en speaker 0"

    captured.clear()
    vocal = make_vocal(bus, {"backend": "sherpa_onnx", "voice_gender": "male"})
    assert captured == [5]
    assert vocal._voice_label == "kokoro-en speaker 5"


def test_vocal_stays_off_in_research_configs():
    assert (
        load_kaine_config(
            profile="thesis_test",
            operator_path="/nonexistent-operator-for-tests.toml",
        )["modules"]["vocal"]
        is False
    )
    assert (
        load_kaine_config(
            operator_path="/nonexistent-operator-for-tests.toml",
        )["modules"]["vocal"]
        is False
    )

    shipped_path = (
        pathlib.Path(__file__).resolve().parents[1] / "config" / "kaine.toml"
    )
    with shipped_path.open("rb") as f:
        raw = tomllib.load(f)
    assert raw["modules"]["vocal"] is False
    vocal_table = raw.get("vocal", {})
    assert "predefined_voice_id" not in vocal_table
    assert "default_voice" not in vocal_table
