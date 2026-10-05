# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import asyncio
import io
import logging
import wave

import numpy as np
import pytest

import kaine.hardware
import kaine.storage
from kaine.modules.audition.emotion import CATEGORIES, Emotion2vecClassifier
from kaine.modules.topos.encoder import InternVideoNextEncoder
from kaine.setup.internvideo_next import internvideo_next_download_cmd


def _tone_wav(frequency: int = 220, duration_s: int = 1, sample_rate: int = 16000) -> bytes:
    n = duration_s * sample_rate
    t = np.arange(n, dtype=np.float32) / sample_rate
    samples = (np.sin(2 * np.pi * frequency * t) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(samples.tobytes())
    return buf.getvalue()


@pytest.mark.asyncio
async def test_emotion2vec_cpu_load_and_classify():
    import torch

    clf = Emotion2vecClassifier(device="cpu")
    # Reproduce the race seen in a multi-module process: another module loading
    # with torch_dtype=float16 switches the process-wide default dtype while
    # emotion2vec builds its model. The classifier must still run in float32.
    previous = torch.get_default_dtype()
    torch.set_default_dtype(torch.float16)
    try:
        await clf.load()
    finally:
        torch.set_default_dtype(previous)
    if not clf.funasr_available:
        pytest.skip("funasr not installed or model not available locally")
    audio = _tone_wav()
    result = await clf.classify(audio, sample_rate=16000)
    assert "inference_failed" not in result.raw
    assert result.category in CATEGORIES


def test_topos_encoder_resolves_weights_under_data_root(tmp_path):
    kaine.storage.set_data_root(tmp_path)
    try:
        encoder = InternVideoNextEncoder()
        with pytest.raises(FileNotFoundError) as exc_info:
            asyncio.run(encoder.load())
        assert str(tmp_path) in str(exc_info.value)
    finally:
        kaine.storage.set_data_root(None)


def test_internvideo_next_download_cmd_uses_data_root(tmp_path):
    kaine.storage.set_data_root(tmp_path)
    try:
        cmd = internvideo_next_download_cmd()
        idx = cmd.index("--local-dir")
        assert idx != -1 and idx + 1 < len(cmd)
        assert str(tmp_path) in cmd[idx + 1]
    finally:
        kaine.storage.set_data_root(None)


def test_resolve_device_logs_actual_fallback_cpu(monkeypatch, caplog):
    monkeypatch.setattr(kaine.hardware, "_cuda_device_count", lambda: 0)
    with caplog.at_level(logging.WARNING, logger="kaine.hardware"):
        resolved = kaine.hardware.resolve_device("cuda:1")
    assert resolved == "cpu"
    assert any(record.message.endswith("falling back to cpu") for record in caplog.records)


def test_topos_encoder_follows_models_dir_set_after_import(tmp_path, monkeypatch):
    # The container sets KAINE_MODELS_DIR for the process; the encoder must read
    # it when it loads, not freeze the weights path when its module is imported.
    models = tmp_path / "models"
    monkeypatch.setenv("KAINE_MODELS_DIR", str(models))
    enc = InternVideoNextEncoder()
    with pytest.raises(FileNotFoundError) as excinfo:
        asyncio.run(enc.load())
    assert str(models) in str(excinfo.value)


def test_topos_loads_float32_on_cpu(monkeypatch):
    import torch

    import kaine.modules.topos.internvideo_next_loader as loader

    seen = {}

    def _capture(**kwargs):
        seen.update(kwargs)
        raise RuntimeError("captured")

    monkeypatch.setattr(loader, "load_internvideo_next", _capture)
    enc = InternVideoNextEncoder(device_preference="cpu")
    with pytest.raises(RuntimeError, match="captured"):
        asyncio.run(enc.load())
    assert seen["torch_dtype"] == torch.float32
