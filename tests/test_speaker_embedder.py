# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Speaker embedding: extractor unit tests, provisioning, and Audition wiring.

Fully offline: sherpa_onnx is replaced by a fake module and the downloader by a
local file copy.
"""

from __future__ import annotations

import dataclasses
import hashlib
import inspect
import io
import shutil
import struct
import wave
from pathlib import Path
from typing import Any

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.audition import Audition, FakeEmotionClassifier, FakeSTTClient
from kaine.modules.audition.speaker_embedder import (
    SpeakerEmbedder,
    SpeakerEmbeddingResult,
)
from kaine.setup.speech_models import MANIFEST, fetch, is_installed, model_dir


def _make_wav(duration_s: float = 1.0, sample_rate: int = 16000) -> bytes:
    n = int(duration_s * sample_rate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack(f"<{n}h", *([0] * n)))
    return buf.getvalue()


class _FakeStream:
    def accept_waveform(self, sample_rate, samples):
        pass

    def input_finished(self):
        pass


class _FakeExtractor:
    dim = 512
    ready = True
    vector: list[float] = [0.1] * 512

    def create_stream(self):
        return _FakeStream()

    def is_ready(self, stream):
        return self.ready

    def compute(self, stream):
        return list(self.vector)


class _FakeConfig:
    def __init__(self, **kw):
        self.kw = kw


class _FakeSherpa:
    """Stands in for the sherpa_onnx module; records builds."""

    SpeakerEmbeddingExtractorConfig = _FakeConfig

    def __init__(self, extractor: _FakeExtractor | None = None) -> None:
        self.extractor = extractor or _FakeExtractor()
        self.builds = 0
        self.last_config: _FakeConfig | None = None

    def SpeakerEmbeddingExtractor(self, config):  # noqa: N802 - mirrors sherpa API
        self.builds += 1
        self.last_config = config
        return self.extractor


def _embedder(sherpa: _FakeSherpa | None = None) -> tuple[SpeakerEmbedder, _FakeSherpa]:
    sherpa = sherpa or _FakeSherpa()
    return SpeakerEmbedder("/fake/model.onnx", sherpa_module=sherpa), sherpa


# ---------------------------------------------------------------------------
# SpeakerEmbedder unit tests
# ---------------------------------------------------------------------------


async def test_extract_returns_embedding():
    emb, _ = _embedder()
    try:
        result = await emb.extract(_make_wav(1.0))
        assert isinstance(result, SpeakerEmbeddingResult)
        assert result.degraded is False
        assert result.dim == 512
        assert result.embedding == pytest.approx([0.1] * 512)
        assert result.confidence > 0
    finally:
        await emb.aclose()


async def test_extract_degraded_when_not_ready():
    ext = _FakeExtractor()
    ext.ready = False
    emb, _ = _embedder(_FakeSherpa(ext))
    try:
        result = await emb.extract(_make_wav(1.0))
        assert result.degraded is True
        assert result.embedding is None
        assert result.confidence == 0.0
    finally:
        await emb.aclose()


async def test_extract_degraded_on_nan():
    ext = _FakeExtractor()
    ext.vector = [0.1] * 511 + [float("nan")]
    emb, _ = _embedder(_FakeSherpa(ext))
    try:
        result = await emb.extract(_make_wav(1.0))
        assert result.degraded is True
        assert result.embedding is None
    finally:
        await emb.aclose()


async def test_extract_degraded_on_empty_audio():
    emb, _ = _embedder()
    try:
        result = await emb.extract(_make_wav(0.0))
        assert result.degraded is True
        assert result.embedding is None
    finally:
        await emb.aclose()


async def test_extract_confidence_scales_with_duration():
    emb, _ = _embedder()
    try:
        short = await emb.extract(_make_wav(0.5))
        long = await emb.extract(_make_wav(3.0))
        assert not short.degraded and not long.degraded
        assert 0 < short.confidence < long.confidence <= 1.0
    finally:
        await emb.aclose()


async def test_warm_up_loads_model():
    emb, sherpa = _embedder()
    try:
        assert emb.loaded is False
        assert sherpa.builds == 0
        await emb.warm_up()
        assert sherpa.builds == 1
        assert emb.loaded is True
        assert emb.dim == 512
        assert sherpa.last_config is not None
        assert sherpa.last_config.kw["model"] == str(Path("/fake/model.onnx"))
        await emb.warm_up()  # idempotent
        assert sherpa.builds == 1
    finally:
        await emb.aclose()


async def test_closed_raises():
    emb, _ = _embedder()
    await emb.aclose()
    with pytest.raises(RuntimeError):
        await emb.extract(_make_wav(1.0))


# ---------------------------------------------------------------------------
# Provisioning
# ---------------------------------------------------------------------------

_MODEL_ID = "wespeaker-cam++-en"


def test_manifest_wespeaker_entry():
    m = MANIFEST[_MODEL_ID]
    assert m.kind == "speaker_embedding"
    assert m.is_single_file is True
    assert m.sha256 == "c46fad10b5f81e1aa4a60c162714208577093655076c5450f8c469e522ec54ef"
    assert m.size_bytes == 29_292_684
    assert m.required_files == ("wespeaker_en_voxceleb_CAM++.onnx",)


def _patch_fake_onnx(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Replace the manifest entry's digest and size with those of a small fake file."""
    src = tmp_path / "fake.onnx"
    src.write_bytes(b"not-a-real-onnx-model" * 10)
    digest = hashlib.sha256(src.read_bytes()).hexdigest()
    monkeypatch.setitem(
        MANIFEST,
        _MODEL_ID,
        dataclasses.replace(
            MANIFEST[_MODEL_ID], sha256=digest, size_bytes=src.stat().st_size
        ),
    )
    return src


def _copy_downloader(src: Path) -> Any:
    def _dl(_url: str, dest: str) -> None:
        shutil.copyfile(str(src), dest)

    return _dl


def test_single_file_fetch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    src = _patch_fake_onnx(monkeypatch, tmp_path)
    root = tmp_path / "root"
    result = fetch(_MODEL_ID, root=root, downloader=_copy_downloader(src))
    assert result.ok, result.detail
    target = model_dir(_MODEL_ID, root)
    assert target.is_dir()
    onnx = target / MANIFEST[_MODEL_ID].archive_name
    assert onnx.read_bytes() == src.read_bytes()
    assert (target / ".verified").is_file()


def test_single_file_fetch_rejects_wrong_size(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    src = _patch_fake_onnx(monkeypatch, tmp_path)
    bad = tmp_path / "bad.onnx"
    bad.write_bytes(b"short")
    result = fetch(_MODEL_ID, root=tmp_path / "root", downloader=_copy_downloader(bad))
    assert not result.ok
    assert "size mismatch" in result.detail
    assert not is_installed(_MODEL_ID, tmp_path / "root")
    assert src.exists()


def test_is_installed_speaker_embedding(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    src = _patch_fake_onnx(monkeypatch, tmp_path)
    root = tmp_path / "root"
    assert is_installed(_MODEL_ID, root) is False
    assert fetch(_MODEL_ID, root=root, downloader=_copy_downloader(src)).ok
    assert is_installed(_MODEL_ID, root) is True


# ---------------------------------------------------------------------------
# Audition integration (bus publish)
# ---------------------------------------------------------------------------

_needs_wiring = pytest.mark.skipif(
    "speaker_embedder" not in inspect.signature(Audition.__init__).parameters,
    reason="Audition does not yet accept speaker_embedder",
)


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


class _StubEmbedder:
    def __init__(self) -> None:
        self.calls = 0

    async def extract(self, audio_bytes: bytes, *, sample_rate: int = 16000):
        self.calls += 1
        return SpeakerEmbeddingResult(
            embedding=[0.1] * 512, confidence=1.0, degraded=False, dim=512
        )

    async def aclose(self) -> None:
        pass


def _make_audition(bus: AsyncBus, **overrides) -> Audition:
    return Audition(
        bus,
        stt_client=FakeSTTClient(responses=["hello world"]),
        emotion_classifier=FakeEmotionClassifier(),
        stt_model="fake-stt",
        transcription_enabled=True,
        **overrides,
    )


async def _event_types(bus: AsyncBus) -> list[str]:
    entries = await bus.read("audition.out", last_id="0", count=50)
    return [e.type for _, e in entries]


@_needs_wiring
async def test_process_audio_publishes_speaker_embedding(bus: AsyncBus):
    stub = _StubEmbedder()
    audition = _make_audition(bus, speaker_embedder=stub)
    await audition.initialize()
    try:
        await audition.process_audio(_make_wav(1.0), sample_rate=16000)
        assert stub.calls == 1
        assert "audition.speaker_embedding" in await _event_types(bus)
    finally:
        await audition.shutdown()


async def test_speaker_embedding_disabled_no_event(bus: AsyncBus):
    audition = _make_audition(bus)
    await audition.initialize()
    try:
        await audition.process_audio(_make_wav(1.0), sample_rate=16000)
        assert "audition.speaker_embedding" not in await _event_types(bus)
    finally:
        await audition.shutdown()
