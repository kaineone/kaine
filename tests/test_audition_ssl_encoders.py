# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import asyncio
import io
import sys
import wave
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from kaine.model_paths import MODELS_DIR_ENV_VAR, models_dir
from kaine.modules.audition.ssl_encoders import (
    DashengAcousticEncoder,
    WavJEPAAcousticEncoder,
)


def _make_wav_bytes(samples: np.ndarray, sample_rate: int = 16000) -> bytes:
    """int16 mono WAV from float32 samples in [-1, 1]."""
    samples = np.clip(samples, -1.0, 1.0)
    pcm = (samples * 32767.0).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


async def _close_module(module: Any) -> None:
    await module.shutdown()
    for task in list(getattr(module, "_tasks", [])):
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


def test_registry_builds_ssl_encoders_without_importing_torch():
    had_torch = "torch" in sys.modules
    from kaine.modules.audition.acoustic import ACOUSTIC_ENCODERS, build_acoustic_encoder

    assert "dasheng" in ACOUSTIC_ENCODERS
    assert "wavjepa" in ACOUSTIC_ENCODERS

    for name in ("dasheng", "wavjepa"):
        enc = build_acoustic_encoder(name)
        assert enc.embedding_dim == 768
        assert enc.model_id
        assert name in enc.model_id

    if had_torch:
        pytest.skip("torch was already imported in this process")
    assert "torch" not in sys.modules


def test_factory_forwards_resolved_device():
    from kaine.modules.audition.acoustic import build_acoustic_encoder

    enc = build_acoustic_encoder("dasheng", device="cuda:2")
    assert enc._device == "cuda:2"
    enc2 = build_acoustic_encoder("wavjepa", device="resolved-device")
    assert enc2._device == "resolved-device"


@pytest.mark.parametrize("cls", [DashengAcousticEncoder, WavJEPAAcousticEncoder])
def test_embed_returns_unit_norm(cls):
    torch = pytest.importorskip("torch")
    hidden = torch.randn(1, 5, 768)

    if cls is DashengAcousticEncoder:

        class FakeModel(torch.nn.Module):
            def __init__(self, hidden):
                super().__init__()
                self._hidden = hidden

            def forward(self, input_values):
                return SimpleNamespace(hidden_states=self._hidden)

        class FakeFE:
            def __call__(self, x, sampling_rate, return_tensors):
                return {"input_values": torch.from_numpy(x)[None, :]}

        encoder = cls(model=FakeModel(hidden), feature_extractor=FakeFE())
    else:

        class FakeModel(torch.nn.Module):
            def __init__(self, hidden):
                super().__init__()
                self._hidden = hidden

            def forward(self, x):
                return self._hidden, None

        encoder = cls(model=FakeModel(hidden))

    wav = _make_wav_bytes(np.random.uniform(-0.1, 0.1, 16000))
    emb = encoder.embed(wav, 16000)
    assert len(emb) == 768
    assert np.all(np.isfinite(emb))
    assert abs(np.linalg.norm(emb) - 1.0) < 1e-5


def test_dasheng_resamples_48k():
    torch = pytest.importorskip("torch")
    pytest.importorskip("torchaudio")
    seen = {}

    class FakeFE:
        def __call__(self, x, sampling_rate, return_tensors):
            seen["samples"] = x.shape[-1]
            return {"input_values": torch.from_numpy(x)[None, :]}

    hidden = torch.randn(1, 4, 768)

    class FakeModel(torch.nn.Module):
        def forward(self, input_values):
            return SimpleNamespace(hidden_states=hidden)

    encoder = DashengAcousticEncoder(
        model=FakeModel(), feature_extractor=FakeFE()
    )
    samples = 48000
    wav = _make_wav_bytes(np.random.uniform(-0.1, 0.1, samples), 48000)
    encoder.embed(wav, 48000)
    assert abs(seen["samples"] - samples * 16000 // 48000) <= 1


def test_wavjepa_resamples_48k():
    torch = pytest.importorskip("torch")
    pytest.importorskip("torchaudio")
    seen = {}

    class FakeModel(torch.nn.Module):
        def forward(self, x):
            seen["shape"] = tuple(x.shape)
            return torch.randn(1, x.shape[-1] // 100, 768), None

    encoder = WavJEPAAcousticEncoder(model=FakeModel())
    samples = 48000
    wav = _make_wav_bytes(np.random.uniform(-0.1, 0.1, samples), 48000)
    encoder.embed(wav, 48000)
    assert seen["shape"] == (1, 1, 16000)


@pytest.mark.parametrize("cls", [DashengAcousticEncoder, WavJEPAAcousticEncoder])
def test_rolling_buffer_capped(cls):
    torch = pytest.importorskip("torch")
    seen = {}

    if cls is DashengAcousticEncoder:

        class FakeFE:
            def __call__(self, x, sampling_rate, return_tensors):
                seen["samples"] = x.shape[-1]
                return {"input_values": torch.from_numpy(x)[None, :]}

        hidden = torch.randn(1, 4, 768)

        class FakeModel(torch.nn.Module):
            def forward(self, input_values):
                return SimpleNamespace(hidden_states=hidden)

        encoder = cls(
            model=FakeModel(), feature_extractor=FakeFE(), context_s=0.5
        )
    else:

        class FakeModel(torch.nn.Module):
            def forward(self, x):
                seen["shape"] = tuple(x.shape)
                return torch.randn(1, x.shape[-1] // 100, 768), None

        encoder = cls(model=FakeModel(), context_s=0.5)

    chunk = _make_wav_bytes(np.random.uniform(-0.1, 0.1, 8000))  # 0.5 s
    encoder.embed(chunk, 16000)
    if cls is DashengAcousticEncoder:
        assert seen["samples"] == 8000
    else:
        assert seen["shape"] == (1, 1, 8000)

    encoder.embed(chunk, 16000)
    if cls is DashengAcousticEncoder:
        assert seen["samples"] == 8000
    else:
        assert seen["shape"] == (1, 1, 8000)


@pytest.mark.parametrize("cls", [DashengAcousticEncoder, WavJEPAAcousticEncoder])
def test_empty_window_returns_zeros_without_calling_model(cls):
    torch = pytest.importorskip("torch")
    calls = [0]

    if cls is DashengAcousticEncoder:

        class FakeFE:
            def __call__(self, x, sampling_rate, return_tensors):
                calls[0] += 1
                return {"input_values": torch.zeros(1, 0)}

        class FakeModel(torch.nn.Module):
            def forward(self, input_values):
                calls[0] += 1
                return SimpleNamespace(hidden_states=torch.zeros(1, 0, 768))

        encoder = cls(model=FakeModel(), feature_extractor=FakeFE())
    else:

        class FakeModel(torch.nn.Module):
            def forward(self, x):
                calls[0] += 1
                return torch.zeros(1, 0, 768), None

        encoder = cls(model=FakeModel())

    emb = encoder.embed(b"", 16000)
    assert emb == [0.0] * 768
    assert calls[0] == 0


def test_nothing_loaded_when_model_injected():
    torch = pytest.importorskip("torch")

    class FakeFE:
        def __call__(self, x, sampling_rate, return_tensors):
            return {"input_values": torch.from_numpy(x)[None, :]}

    hidden = torch.randn(1, 3, 768)

    class FakeModel(torch.nn.Module):
        def forward(self, input_values):
            return SimpleNamespace(hidden_states=hidden)

    encoder = DashengAcousticEncoder(
        model=FakeModel(), feature_extractor=FakeFE()
    )
    wav = _make_wav_bytes(np.random.uniform(-0.1, 0.1, 16000))
    encoder.embed(wav, 16000)
    assert encoder._model is not None
    assert encoder._feature_extractor is not None
    assert encoder._weights_dir is None


@pytest.mark.parametrize("cls", [DashengAcousticEncoder, WavJEPAAcousticEncoder])
def test_missing_weights_raises_file_not_found(cls, tmp_path, monkeypatch):
    pytest.importorskip("torch")
    monkeypatch.setenv(MODELS_DIR_ENV_VAR, str(tmp_path))
    encoder = cls()
    wav = _make_wav_bytes(np.random.uniform(-0.1, 0.1, 16000))
    with pytest.raises(FileNotFoundError) as exc_info:
        encoder.embed(wav, 16000)
    msg = str(exc_info.value)
    assert "model.safetensors" in msg
    assert "python -m kaine.setup.audio_ssl" in msg
    assert str(tmp_path) in msg


@pytest.mark.parametrize("cls", [DashengAcousticEncoder, WavJEPAAcousticEncoder])
def test_wrong_revision_raises_value_error(cls, tmp_path):
    pytest.importorskip("torch")
    weights_dir = tmp_path / ("dasheng_base" if cls is DashengAcousticEncoder else "wavjepa_base")
    weights_dir.mkdir(parents=True)
    (weights_dir / "model.safetensors").write_bytes(b"not a real checkpoint")
    (weights_dir / "REVISION").write_text("deadbeefdeadbeefdeadbeefdeadbeefdeadbeef")
    encoder = cls(weights_dir=weights_dir)
    wav = _make_wav_bytes(np.random.uniform(-0.1, 0.1, 16000))
    with pytest.raises(ValueError) as exc_info:
        encoder.embed(wav, 16000)
    assert "REVISION" in str(exc_info.value)


@pytest.mark.asyncio
async def test_zero_persistence_with_dasheng_encoder(bus):
    torch = pytest.importorskip("torch")

    class FakeFE:
        def __call__(self, x, sampling_rate, return_tensors):
            return {"input_values": torch.from_numpy(x)[None, :]}

    hidden = torch.randn(1, 5, 768)

    class FakeModel(torch.nn.Module):
        def forward(self, input_values):
            return SimpleNamespace(hidden_states=hidden)

    encoder = DashengAcousticEncoder(model=FakeModel(), feature_extractor=FakeFE())
    from kaine.modules.audition import Audition, FakeEmotionClassifier, FakeSTTClient

    audition = Audition(
        bus,
        general_audition=True,
        acoustic_encoder=encoder,
        stt_client=FakeSTTClient(),
        emotion_classifier=FakeEmotionClassifier(),
        stt_model="fake-stt",
        transcription_enabled=False,
    )
    await audition.initialize()
    try:
        for i in range(3):
            wav = _make_wav_bytes(np.random.uniform(-0.1, 0.1, 8000))
            await audition._perceive_acoustic(wav, 16000, "seeded")
        state = audition.serialize()
    finally:
        await _close_module(audition)

    # No path or file handle should survive on the encoder.
    assert getattr(encoder, "_weights_dir", None) is None

    def _walk(obj, path="root"):
        if isinstance(obj, bytes):
            raise AssertionError(f"bytes at {path}")
        if isinstance(obj, list):
            if (
                obj
                and all(isinstance(v, (int, float)) for v in obj)
                and len(obj) > 768
                and "layers" not in path
            ):
                raise AssertionError(
                    f"unexpected long numeric vector at {path} "
                    f"({len(obj)} > 768)"
                )
            for i, v in enumerate(obj):
                _walk(v, f"{path}[{i}]")
        elif isinstance(obj, dict):
            for k, v in obj.items():
                _walk(v, f"{path}[{k!r}]")

    _walk(state)


def _cosine(a, b):
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))


@pytest.mark.skipif(
    not (models_dir() / "dasheng_base" / "model.safetensors").exists(),
    reason="dasheng weights not provisioned",
)
def test_dasheng_real_weights_tone_vs_noise():
    pytest.importorskip("torch")
    pytest.importorskip("safetensors")
    tone = np.sin(2 * np.pi * 440 * np.linspace(0, 1, 16000, endpoint=False))
    noise = np.random.default_rng(42).uniform(-0.5, 0.5, 16000)

    enc = DashengAcousticEncoder()
    e_tone = enc.embed(_make_wav_bytes(tone), 16000)
    e_noise = enc.embed(_make_wav_bytes(noise), 16000)

    assert len(e_tone) == 768
    assert len(e_noise) == 768
    assert np.all(np.isfinite(e_tone))
    assert np.all(np.isfinite(e_noise))
    assert abs(np.linalg.norm(e_tone) - 1.0) < 1e-5
    assert abs(np.linalg.norm(e_noise) - 1.0) < 1e-5
    assert _cosine(e_tone, e_noise) < 0.99

    enc2 = DashengAcousticEncoder()
    e_tone2 = enc2.embed(_make_wav_bytes(tone), 16000)
    assert e_tone == e_tone2


@pytest.mark.skipif(
    not (models_dir() / "wavjepa_base" / "model.safetensors").exists(),
    reason="wavjepa weights not provisioned",
)
def test_wavjepa_real_weights_tone_vs_noise():
    pytest.importorskip("torch")
    pytest.importorskip("safetensors")
    tone = np.sin(2 * np.pi * 440 * np.linspace(0, 1, 16000, endpoint=False))
    noise = np.random.default_rng(42).uniform(-0.5, 0.5, 16000)

    enc = WavJEPAAcousticEncoder()
    e_tone = enc.embed(_make_wav_bytes(tone), 16000)
    e_noise = enc.embed(_make_wav_bytes(noise), 16000)

    assert len(e_tone) == 768
    assert len(e_noise) == 768
    assert np.all(np.isfinite(e_tone))
    assert np.all(np.isfinite(e_noise))
    assert abs(np.linalg.norm(e_tone) - 1.0) < 1e-5
    assert abs(np.linalg.norm(e_noise) - 1.0) < 1e-5
    assert _cosine(e_tone, e_noise) < 0.99

    enc2 = WavJEPAAcousticEncoder()
    e_tone2 = enc2.embed(_make_wav_bytes(tone), 16000)
    assert e_tone == e_tone2

    inner = enc._model.model
    assert inner.teacher_encoder is None
    assert inner.decoder is None
    assert inner.decoder_to_encoder_mapper is None
    assert inner.encoder_to_decoder_mapper is None


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = Any  # placeholder for import below
    from kaine.bus.client import AsyncBus
    from kaine.bus.config import BusConfig

    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def test_factory_passes_the_resolved_device_to_the_encoder(monkeypatch):
    import kaine.boot.factories.audition as factory_mod

    seen = []

    def fake_resolve(device):
        seen.append(device)
        return "cuda:7"

    monkeypatch.setattr(factory_mod, "resolve_device", fake_resolve)
    captured = {}

    def fake_build(name, **kwargs):
        captured["name"] = name
        captured.update(kwargs)
        from kaine.modules.audition.acoustic import FakeAcousticEncoder

        return FakeAcousticEncoder(8)

    import kaine.modules.audition.acoustic as acoustic_mod

    monkeypatch.setattr(acoustic_mod, "build_acoustic_encoder", fake_build)
    section = {"general_audition": True, "acoustic_encoder": "dasheng", "acoustic_device": "cuda:1"}
    factory_mod.make_audition(None, section)
    assert seen == ["cuda:1"]
    assert captured == {"name": "dasheng", "device": "cuda:7"}
