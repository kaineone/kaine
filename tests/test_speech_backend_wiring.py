# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import importlib.util
import inspect
from types import SimpleNamespace

import pytest

import kaine.cycle.__main__ as cycle_main
from kaine.backend_state import backend_failures, clear_backend_failures
from kaine.boot import ConfigurationError, build_registry, make_audition, make_vox
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.audition import FakeEmotionClassifier, FakeSTTClient
from kaine.modules.audition.module import Audition
from kaine.modules.audition.stt_client import SpeachesClient, TranscriptionResult
from kaine.modules.vox.client import ChatterboxClient, SynthesisResult
from kaine.modules.vox.mapping import ChatterboxParams
from kaine.modules.vox.module import CHATTERBOX_PROSODY, Vox
from kaine.modules.vox.sherpa_tts import APPLIED_PROSODY


def _backend_failure(module: str, backend: str):
    for record in backend_failures():
        if record.module == module and record.backend == backend:
            return record
    return None


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


def test_make_audition_default_uses_speaches(bus):
    audition = make_audition(bus, {"perception_feed": {}})
    assert isinstance(audition, Audition)
    assert isinstance(audition._stt_client, SpeachesClient)
    assert audition._backend == "speaches"
    assert audition._transcription_enabled is False


def test_make_audition_sherpa_onnx(bus, monkeypatch):
    calls = []

    class FakeSherpa:
        def __init__(self, model_dir, *, model_id, num_threads):
            calls.append(
                {"model_dir": model_dir, "model_id": model_id, "num_threads": num_threads}
            )

    monkeypatch.setattr(
        "kaine.modules.audition.sherpa_stt.SherpaMoonshineSTT", FakeSherpa
    )
    monkeypatch.setattr(
        "kaine.model_paths.speech_model_dir", lambda _id: f"/fake/models/{_id}"
    )
    monkeypatch.setattr("kaine.model_paths.DEFAULT_STT", "moonshine-base-en")

    audition = make_audition(
        bus, {"backend": "sherpa_onnx", "transcription_enabled": True, "perception_feed": {}}
    )
    assert isinstance(audition, Audition)
    assert audition._backend == "sherpa_onnx"
    assert audition._stt_model == "moonshine-base-en"
    assert len(calls) == 1
    assert calls[0]["model_dir"] == "/fake/models/moonshine-base-en"
    assert calls[0]["model_id"] == "moonshine-base-en"
    assert calls[0]["num_threads"] == 2

    calls.clear()
    make_audition(
        bus,
        {
            "backend": "sherpa_onnx",
            "transcription_enabled": True,
            "sherpa_model_id": "moonshine-tiny-en",
            "sherpa_num_threads": 4,
            "perception_feed": {},
        },
    )
    assert len(calls) == 1
    assert calls[0]["model_dir"] == "/fake/models/moonshine-tiny-en"
    assert calls[0]["model_id"] == "moonshine-tiny-en"
    assert calls[0]["num_threads"] == 4


def test_make_audition_unknown_backend_raises(bus):
    with pytest.raises(ConfigurationError):
        make_audition(bus, {"backend": "whisper", "perception_feed": {}})


def test_make_audition_sherpa_failure_disables_transcription(bus, monkeypatch, caplog):
    class BrokenSherpa:
        def __init__(self, *args, **kwargs):
            raise FileNotFoundError("model files missing")

    monkeypatch.setattr(
        "kaine.modules.audition.sherpa_stt.SherpaMoonshineSTT", BrokenSherpa
    )
    monkeypatch.setattr(
        "kaine.model_paths.speech_model_dir", lambda _id: f"/fake/models/{_id}"
    )
    monkeypatch.setattr("kaine.model_paths.DEFAULT_STT", "moonshine-base-en")

    result = make_audition(
        bus, {"backend": "sherpa_onnx", "transcription_enabled": True, "perception_feed": {}}
    )
    assert isinstance(result, Audition)
    assert result._transcription_enabled is False
    assert result._backend == "sherpa_onnx"
    assert result._stt_model == "moonshine-base-en"
    failure = _backend_failure("audition", "sherpa_onnx")
    assert failure is not None
    assert "model files missing" in failure.reason
    assert "sherpa-onnx transcription unavailable" in caplog.text
    assert "python -m kaine.setup.speech_models --stt moonshine-base-en" in caplog.text


def test_make_audition_transcription_off_with_sherpa_onnx_does_not_resolve(bus, monkeypatch):
    calls = []

    class FakeSherpa:
        def __init__(self, *args, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(
        "kaine.modules.audition.sherpa_stt.SherpaMoonshineSTT", FakeSherpa
    )

    audition = make_audition(bus, {"backend": "sherpa_onnx", "perception_feed": {}})
    assert isinstance(audition, Audition)
    assert audition._backend == "sherpa_onnx"
    assert audition._transcription_enabled is False
    assert calls == []


def test_make_vox_default_uses_chatterbox(bus):
    vox = make_vox(bus, {})
    assert isinstance(vox, Vox)
    assert isinstance(vox._tts_client, ChatterboxClient)
    assert vox._backend == "chatterbox"
    assert vox._applied_prosody == CHATTERBOX_PROSODY


def test_make_vox_sherpa_onnx(bus, monkeypatch):
    calls = []

    class FakeSherpa:
        def __init__(self, model_dir, *, model_id, speaker_id, num_threads):
            calls.append(
                {
                    "model_dir": model_dir,
                    "model_id": model_id,
                    "speaker_id": speaker_id,
                    "num_threads": num_threads,
                }
            )

    monkeypatch.setattr("kaine.modules.vox.sherpa_tts.SherpaKokoroTTS", FakeSherpa)
    monkeypatch.setattr(
        "kaine.model_paths.speech_model_dir", lambda _id: f"/fake/models/{_id}"
    )
    monkeypatch.setattr("kaine.model_paths.DEFAULT_TTS", "kokoro-en")

    vox = make_vox(bus, {"backend": "sherpa_onnx"})
    assert isinstance(vox, Vox)
    assert vox._backend == "sherpa_onnx"
    assert vox._applied_prosody == APPLIED_PROSODY
    assert vox._voice_label == "kokoro-en speaker 0"
    assert len(calls) == 1
    assert calls[0]["model_dir"] == "/fake/models/kokoro-en"
    assert calls[0]["model_id"] == "kokoro-en"
    assert calls[0]["speaker_id"] == 0
    assert calls[0]["num_threads"] == 2

    calls.clear()
    vox2 = make_vox(
        bus,
        {
            "backend": "sherpa_onnx",
            "sherpa_model_id": "kokoro-en",
            "sherpa_speaker_id": 7,
            "sherpa_num_threads": 8,
        },
    )
    assert vox2._voice_label == "kokoro-en speaker 7"
    assert len(calls) == 1
    assert calls[0]["speaker_id"] == 7
    assert calls[0]["num_threads"] == 8


def test_make_vox_unknown_backend_raises(bus):
    with pytest.raises(ConfigurationError):
        make_vox(bus, {"backend": "piper"})


def test_make_vox_sherpa_failure_records_and_returns_none(bus, monkeypatch):
    class BrokenSherpa:
        def __init__(self, *args, **kwargs):
            raise FileNotFoundError("model files missing")

    monkeypatch.setattr("kaine.modules.vox.sherpa_tts.SherpaKokoroTTS", BrokenSherpa)
    monkeypatch.setattr(
        "kaine.model_paths.speech_model_dir", lambda _id: f"/fake/models/{_id}"
    )

    result = make_vox(bus, {"backend": "sherpa_onnx"})
    assert result is None
    failure = _backend_failure("vox", "sherpa_onnx")
    assert failure is not None
    assert "model files missing" in str(failure.get("reason") if isinstance(failure, dict) else failure)


def test_make_vox_normalises_backend_and_prosody(bus, monkeypatch):
    calls = []

    class FakeSherpa:
        def __init__(self, *args, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr("kaine.modules.vox.sherpa_tts.SherpaKokoroTTS", FakeSherpa)
    monkeypatch.setattr(
        "kaine.model_paths.speech_model_dir", lambda _id: f"/fake/models/{_id}"
    )
    monkeypatch.setattr("kaine.model_paths.DEFAULT_TTS", "kokoro-en")

    vox = make_vox(bus, {"backend": "chatterbox "})
    assert isinstance(vox, Vox)
    assert vox._backend == "chatterbox"
    assert vox._applied_prosody == CHATTERBOX_PROSODY
    # The Chatterbox path keeps the configured voice id; no label masks it.
    assert vox._voice_label is None
    assert calls == []

    calls.clear()
    vox2 = make_vox(bus, {"backend": " sherpa_onnx"})
    assert isinstance(vox2, Vox)
    assert vox2._backend == "sherpa_onnx"
    assert vox2._applied_prosody == APPLIED_PROSODY
    assert vox2._voice_label == "kokoro-en speaker 0"
    assert len(calls) == 1


async def _call_build_registry(bus, config):
    kwargs = {}
    params = inspect.signature(build_registry).parameters
    if "intent_secret" in params:
        kwargs["intent_secret"] = None
    if "plugins" in params:
        kwargs["plugins"] = []
    if inspect.iscoroutinefunction(build_registry):
        return await build_registry(bus, config, **kwargs)
    return build_registry(bus, config, **kwargs)


@pytest.mark.asyncio
async def test_build_registry_registers_audition_despite_sherpa_failure(bus, monkeypatch):
    class BrokenSherpa:
        def __init__(self, *args, **kwargs):
            raise FileNotFoundError("no model files")

    monkeypatch.setattr(
        "kaine.modules.audition.sherpa_stt.SherpaMoonshineSTT", BrokenSherpa
    )
    monkeypatch.setattr(
        "kaine.model_paths.speech_model_dir", lambda _id: f"/fake/models/{_id}"
    )
    monkeypatch.setattr("kaine.extras.check", lambda cfg: [])

    config = {
        "modules": {"audition": True, "vox": True},
        "audition": {"backend": "sherpa_onnx", "transcription_enabled": True},
        "vox": {},
        "perception_feed": {},
    }
    registry = await _call_build_registry(bus, config)
    assert "audition" in registry
    assert "vox" in registry
    assert registry.get("audition")._transcription_enabled is False
    assert registry.get("audition")._backend == "sherpa_onnx"


@pytest.mark.asyncio
async def test_build_registry_refuses_boot_when_sherpa_package_missing(bus, monkeypatch):
    real_find_spec = importlib.util.find_spec

    def fake_find_spec(name):
        if name == "sherpa_onnx":
            return None
        return real_find_spec(name)

    monkeypatch.setattr("importlib.util.find_spec", fake_find_spec)

    config = {
        "modules": {"audition": True, "vox": True},
        "audition": {"backend": "sherpa_onnx", "transcription_enabled": True},
        "vox": {},
        "perception_feed": {},
    }
    with pytest.raises(ConfigurationError, match="speech-edge"):
        await _call_build_registry(bus, config)


def test_rebuild_module_raises_when_construct_returns_none(bus, monkeypatch):
    monkeypatch.setattr(cycle_main, "construct_module", lambda *args, **kwargs: None)
    registry = SimpleNamespace(entity_clock=None, plugins=[])
    rebuild = cycle_main._make_rebuild_module(bus, {}, registry, None)
    with pytest.raises(RuntimeError, match="cannot rebuild audition"):
        rebuild("audition")


@pytest.mark.asyncio
async def test_audition_transcription_event_discloses_backend(bus, monkeypatch):
    captured = []
    stt_model = "fake-stt"

    async def fake_publish(channel, payload, *, salience=None):
        captured.append((channel, payload))

    audition = Audition(
        bus,
        stt_client=FakeSTTClient(responses=["hello world"]),
        backend="sherpa_onnx",
        emotion_classifier=FakeEmotionClassifier(),
        stt_model=stt_model,
        transcription_enabled=True,
    )
    monkeypatch.setattr(audition, "publish", fake_publish)

    result = TranscriptionResult(text="hello", model="fake-model", latency_ms=10.0, raw={})
    await audition._publish_transcription(result, "mic", 16000, 32000)
    assert captured[-1][0] == "audition.transcription"
    assert captured[-1][1]["backend"] == "sherpa_onnx"
    # A successful transcription reports the model that produced it.
    assert captured[-1][1]["model"] == result.model

    captured.clear()
    await audition._publish_transcription_error(
        source_label="mic",
        sample_rate=16000,
        audio_bytes_length=32000,
        exc=RuntimeError("stt failed"),
    )
    assert captured[-1][0] == "audition.transcription"
    assert captured[-1][1]["backend"] == "sherpa_onnx"
    assert captured[-1][1]["model"] == stt_model
    assert captured[-1][1]["alert"] is True

    captured.clear()
    await audition._publish_emotion_error(source_label="mic", exc=RuntimeError("ser failed"))
    assert captured[-1][0] == "audition.emotion"
    assert captured[-1][1]["alert"] is True


@pytest.mark.asyncio
async def test_vox_synthesized_event_discloses_backend(bus, monkeypatch):
    captured = []

    async def fake_publish(channel, payload, *, salience=None):
        captured.append((channel, payload))

    vox = Vox(
        bus,
        backend="sherpa_onnx",
        applied_prosody=APPLIED_PROSODY,
        voice_label="kokoro-en speaker 0",
    )
    monkeypatch.setattr(vox, "publish", fake_publish)

    params = ChatterboxParams(
        temperature=0.7, exaggeration=0.5, cfg_weight=0.5, speed_factor=1.0
    )
    result = SynthesisResult(
        audio=b"audio",
        content_type="audio/wav",
        latency_ms=5.0,
        output_format="wav",
        bytes_produced=100,
    )
    await vox._publish_event("hello", params, result, success=True)
    payload = captured[-1][1]
    assert payload["backend"] == "sherpa_onnx"
    assert payload["prosody_applied"] == ["speed_factor"]
    assert payload["voice"] == "kokoro-en speaker 0"

    vox_default = Vox(bus)
    captured.clear()
    monkeypatch.setattr(vox_default, "publish", fake_publish)
    await vox_default._publish_event("hi", params, result, success=True)
    payload = captured[-1][1]
    assert payload["backend"] == "chatterbox"
    assert payload["prosody_applied"] == [
        "temperature",
        "exaggeration",
        "cfg_weight",
        "speed_factor",
    ]
    assert payload["voice"] == "(default)"


def test_extras_audition_sherpa_requires_transcription_enabled():
    from kaine.extras import _audition_sherpa

    assert _audition_sherpa({"audition": {"backend": "sherpa_onnx", "transcription_enabled": True}})
    assert not _audition_sherpa({"audition": {"backend": "sherpa_onnx"}})
    assert not _audition_sherpa({"audition": {"backend": "sherpa_onnx", "transcription_enabled": False}})
    assert not _audition_sherpa({"audition": {"backend": "speaches", "transcription_enabled": True}})


def test_extras_vox_sherpa_normalised():
    from kaine.extras import _vox_sherpa

    assert _vox_sherpa({"vox": {"backend": "sherpa_onnx"}})
    assert _vox_sherpa({"vox": {"backend": "Sherpa_ONNX "}})
    assert not _vox_sherpa({"vox": {}})
    assert not _vox_sherpa({"vox": {"backend": "chatterbox"}})
