# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Residency-contract tests for perception encoders and the emotion classifier.

Verifies reversible unload, safetensors-only weights, lazy loading, and
in-flight protection for the Topos encoders and Emotion2vecClassifier.
"""

from __future__ import annotations

import asyncio
import sys
import threading
from types import SimpleNamespace
from typing import Any

import pytest
import torch
from PIL import Image

from kaine.modules.audition.emotion import Emotion2vecClassifier
from kaine.modules.topos.encoder import DINOv2Encoder, InternVideoNextEncoder
from kaine.modules.topos.internvideo_next_loader import WEIGHTS_FILENAME

# --------------------------------------------------------------------------
# Emotion classifier
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emotion_classify_reload_after_shutdown_and_failure(monkeypatch):
    """Happy path survives shutdown/unload; a load failure degrades permanently."""
    load_calls: list[dict] = []

    class HappyAutoModel:
        def __init__(self, **kwargs):
            load_calls.append(kwargs)

        def generate(self, *, input, granularity, extract_embedding):
            return [{"labels": ["/happy/"], "scores": [0.9]}]

    monkeypatch.setitem(sys.modules, "funasr", SimpleNamespace(AutoModel=HappyAutoModel))

    classifier = Emotion2vecClassifier()
    result = await classifier.classify(b"\x00", sample_rate=16000)
    assert result.category == "happy"
    assert result.raw.get("degraded") is None

    await classifier.shutdown()
    result2 = await classifier.classify(b"\x00", sample_rate=16000)
    assert result2.category == "happy"

    await classifier.unload()
    assert classifier.loaded is False
    result3 = await classifier.classify(b"\x00", sample_rate=16000)
    assert result3.category == "happy"

    assert len(load_calls) == 3

    # Failure path: AutoModel raises once; subsequent calls stay degraded.
    raise_calls = []

    class RaisingAutoModel:
        def __init__(self, **kwargs):
            raise_calls.append(kwargs)
            raise RuntimeError("model load failure")

    monkeypatch.setitem(sys.modules, "funasr", SimpleNamespace(AutoModel=RaisingAutoModel))

    failing_classifier = Emotion2vecClassifier()
    degraded = await failing_classifier.classify(b"\x00", sample_rate=16000)
    assert degraded.category == "neutral"
    assert degraded.confidence == 0.0
    assert degraded.raw.get("degraded") is True
    assert failing_classifier.funasr_available is False

    degraded2 = await failing_classifier.classify(b"\x00", sample_rate=16000)
    assert degraded2.category == "neutral"
    assert len(raise_calls) == 1


@pytest.mark.asyncio
async def test_emotion_unload_waits_for_inflight(monkeypatch):
    """unload() blocks until an in-flight classify finishes."""
    loop = asyncio.get_running_loop()
    entered = threading.Event()
    aio_event = asyncio.Event()

    class BlockingAutoModel:
        def __init__(self, **kwargs):
            pass

        def generate(self, *, input, granularity, extract_embedding):
            loop.call_soon_threadsafe(aio_event.set)
            entered.wait()
            return [{"labels": ["/happy/"], "scores": [0.9]}]

    monkeypatch.setitem(sys.modules, "funasr", SimpleNamespace(AutoModel=BlockingAutoModel))

    classifier = Emotion2vecClassifier()

    classify_task = asyncio.create_task(
        asyncio.wait_for(classifier.classify(b"\x00", sample_rate=16000), timeout=5)
    )
    try:
        await asyncio.wait_for(aio_event.wait(), timeout=5)

        unload_task = asyncio.create_task(asyncio.wait_for(classifier.unload(), timeout=5))
        await asyncio.sleep(0.05)
        assert not unload_task.done()
        # The model is still held while the inference is in flight.
        assert classifier.loaded
    finally:
        # Always release the fake inference thread, so a failure fails
        # instead of hanging the interpreter at exit.
        entered.set()

    result = await classify_task
    assert result.category == "happy"
    await unload_task
    assert classifier.loaded is False


@pytest.mark.asyncio
async def test_emotion_unload_in_gap(monkeypatch):
    """A concurrent unload between load and use does not crash the classify."""
    class HappyAutoModel:
        def __init__(self, **kwargs):
            pass

        def generate(self, *, input, granularity, extract_embedding):
            return [{"labels": ["/happy/"], "scores": [0.9]}]

    monkeypatch.setitem(sys.modules, "funasr", SimpleNamespace(AutoModel=HappyAutoModel))

    classifier = Emotion2vecClassifier()
    original = classifier.ensure_loaded

    async def wrapped():
        await original()
        await classifier.unload()

    classifier.ensure_loaded = wrapped

    # Force a load+unload cycle before the actual classify.
    await classifier.ensure_loaded()
    result = await classifier.classify(b"\x00", sample_rate=16000)
    assert result.category == "happy"


@pytest.mark.asyncio
async def test_emotion_double_cancel_does_not_leak_inflight(monkeypatch):
    """A twice-cancelled in-flight classify releases the in-flight count."""
    loop = asyncio.get_running_loop()
    entered = threading.Event()
    aio_event = asyncio.Event()

    class BlockingAutoModel:
        def __init__(self, **kwargs):
            pass

        def generate(self, *, input, granularity, extract_embedding):
            loop.call_soon_threadsafe(aio_event.set)
            entered.wait()
            return [{"labels": ["/happy/"], "scores": [0.9]}]

    monkeypatch.setitem(sys.modules, "funasr", SimpleNamespace(AutoModel=BlockingAutoModel))

    classifier = Emotion2vecClassifier()
    classify_task = asyncio.create_task(classifier.classify(b"\x00", sample_rate=16000))
    try:
        await asyncio.wait_for(aio_event.wait(), timeout=5)

        lock = classifier._lock()
        await lock.acquire()
        try:
            classify_task.cancel()
            await asyncio.sleep(0)
            classify_task.cancel()
            await asyncio.sleep(0)
        finally:
            lock.release()
    finally:
        entered.set()

    with pytest.raises(asyncio.CancelledError):
        await classify_task

    await asyncio.wait_for(classifier.unload(), timeout=2)
    assert classifier._gate.inflight == 0


@pytest.mark.asyncio
async def test_emotion_cancelled_inference_unload_waits_for_worker(monkeypatch):
    """A cancelled in-flight classify keeps the model loaded until the worker exits."""
    loop = asyncio.get_running_loop()
    entered = threading.Event()
    aio_event = asyncio.Event()
    unload_task: asyncio.Task | None = None

    class BlockingAutoModel:
        def __init__(self, **kwargs):
            pass

        def generate(self, *, input, granularity, extract_embedding):
            loop.call_soon_threadsafe(aio_event.set)
            entered.wait()
            return [{"labels": ["/happy/"], "scores": [0.9]}]

    monkeypatch.setitem(sys.modules, "funasr", SimpleNamespace(AutoModel=BlockingAutoModel))

    classifier = Emotion2vecClassifier()
    classify_task = asyncio.create_task(classifier.classify(b"\x00", sample_rate=16000))
    try:
        await asyncio.wait_for(aio_event.wait(), timeout=5)

        classify_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await classify_task

        unload_task = asyncio.create_task(asyncio.wait_for(classifier.unload(), timeout=5))
        await asyncio.sleep(0.1)
        assert not unload_task.done()
        assert classifier.loaded
        assert classifier._gate.inflight == 1
    finally:
        entered.set()

    assert unload_task is not None
    await asyncio.wait_for(unload_task, timeout=5)
    assert not classifier.loaded


# --------------------------------------------------------------------------
# Topos encoders
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_internvideo_next_unload_and_reload(monkeypatch):
    """InternVideo-Next reloads after unload and keeps latent_dim."""
    loader_calls: list[dict] = []

    def fake_loader(**kwargs):
        loader_calls.append(kwargs)
        return object()

    def fake_processor(*args, **kwargs):
        return {"pixel_values": torch.zeros(1, 16, 3, 224, 224)}

    monkeypatch.setattr(
        "kaine.modules.topos.internvideo_next_loader.load_internvideo_next",
        fake_loader,
    )
    monkeypatch.setattr(
        "kaine.modules.topos.encoder._load_videomae_processor",
        fake_processor,
    )

    encoder = InternVideoNextEncoder(device_preference="cpu", clip_len=16)
    encoder._forward_clip = lambda frames, **kwargs: [1.0] * 768

    await encoder.load()
    assert encoder.loaded is True
    assert encoder.latent_dim == 768

    await encoder.unload()
    assert encoder.loaded is False
    assert encoder.latent_dim == 768

    frames = [Image.new("RGB", (224, 224), color=(128, 128, 128)) for _ in range(16)]
    result = await encoder.encode_clip(frames)
    assert result == [1.0] * 768
    assert len(loader_calls) == 2


@pytest.mark.asyncio
async def test_dinov2_uses_safetensors_and_reloads(monkeypatch):
    """DINOv2 passes use_safetensors=True and survives unload/reload."""
    recorded: dict[str, Any] = {}

    class FakeProcessor:
        def __call__(self, *, images, return_tensors):
            return {"pixel_values": torch.zeros(1, 3, 224, 224)}

    class FakeAutoImageProcessor:
        @classmethod
        def from_pretrained(cls, model_id, **kwargs):
            return FakeProcessor()

    class FakeModel:
        def __init__(self, model_id, **kwargs):
            recorded["model_kwargs"] = kwargs

        def to(self, device):
            return self

        def eval(self):
            return self

        def parameters(self):
            return iter([torch.nn.Parameter(torch.zeros(1))])

        def __call__(self, **kwargs):
            return SimpleNamespace(last_hidden_state=torch.randn(1, 197, 384))

    class FakeAutoModel:
        @classmethod
        def from_pretrained(cls, model_id, **kwargs):
            return FakeModel(model_id, **kwargs)

    fake_transformers = SimpleNamespace(
        AutoImageProcessor=FakeAutoImageProcessor,
        AutoModel=FakeAutoModel,
    )
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)

    encoder = DINOv2Encoder(device_preference="cpu")
    await encoder.load()
    assert encoder.loaded is True
    assert encoder.latent_dim == 384
    assert recorded.get("model_kwargs", {}).get("use_safetensors") is True

    await encoder.unload()
    assert encoder.loaded is False

    await encoder.load()
    assert encoder.loaded is True


@pytest.mark.asyncio
async def test_dinov2_double_cancel_does_not_leak_inflight(monkeypatch):
    """A twice-cancelled in-flight encode releases the in-flight count."""
    loop = asyncio.get_running_loop()
    entered = threading.Event()
    aio_event = asyncio.Event()

    class FakeProcessor:
        def __call__(self, *, images, return_tensors):
            return {"pixel_values": torch.zeros(1, 3, 224, 224)}

    class FakeAutoImageProcessor:
        @classmethod
        def from_pretrained(cls, model_id, **kwargs):
            return FakeProcessor()

    class FakeModel:
        def __init__(self, model_id, **kwargs):
            pass

        def to(self, device):
            return self

        def eval(self):
            return self

        def parameters(self):
            return iter([torch.nn.Parameter(torch.zeros(1))])

        def __call__(self, **kwargs):
            return SimpleNamespace(last_hidden_state=torch.randn(1, 197, 384))

    class FakeAutoModel:
        @classmethod
        def from_pretrained(cls, model_id, **kwargs):
            return FakeModel(model_id, **kwargs)

    fake_transformers = SimpleNamespace(
        AutoImageProcessor=FakeAutoImageProcessor,
        AutoModel=FakeAutoModel,
    )
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)

    encoder = DINOv2Encoder(device_preference="cpu")
    await encoder.load()

    FakeModel.__call__ = lambda self, **kwargs: (
        loop.call_soon_threadsafe(aio_event.set),
        entered.wait(),
        SimpleNamespace(last_hidden_state=torch.randn(1, 197, 384)),
    )[-1]

    image = Image.new("RGB", (224, 224), color=(128, 128, 128))
    encode_task = asyncio.create_task(encoder.encode(image))
    try:
        await asyncio.wait_for(aio_event.wait(), timeout=5)

        lock = encoder._get_lock()
        await lock.acquire()
        try:
            encode_task.cancel()
            await asyncio.sleep(0)
            encode_task.cancel()
            await asyncio.sleep(0)
        finally:
            lock.release()
    finally:
        entered.set()

    with pytest.raises(asyncio.CancelledError):
        await encode_task

    await asyncio.wait_for(encoder.unload(), timeout=2)
    assert encoder._gate.inflight == 0


@pytest.mark.asyncio
async def test_dinov2_cancelled_inference_unload_waits_for_worker(monkeypatch):
    """A cancelled in-flight encode keeps the model loaded until the worker exits."""
    loop = asyncio.get_running_loop()
    entered = threading.Event()
    aio_event = asyncio.Event()
    unload_task: asyncio.Task | None = None

    class FakeProcessor:
        def __call__(self, *, images, return_tensors):
            return {"pixel_values": torch.zeros(1, 3, 224, 224)}

    class FakeAutoImageProcessor:
        @classmethod
        def from_pretrained(cls, model_id, **kwargs):
            return FakeProcessor()

    class FakeModel:
        def __init__(self, model_id, **kwargs):
            pass

        def to(self, device):
            return self

        def eval(self):
            return self

        def parameters(self):
            return iter([torch.nn.Parameter(torch.zeros(1))])

        def __call__(self, **kwargs):
            return SimpleNamespace(last_hidden_state=torch.randn(1, 197, 384))

    class FakeAutoModel:
        @classmethod
        def from_pretrained(cls, model_id, **kwargs):
            return FakeModel(model_id, **kwargs)

    fake_transformers = SimpleNamespace(
        AutoImageProcessor=FakeAutoImageProcessor,
        AutoModel=FakeAutoModel,
    )
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)

    encoder = DINOv2Encoder(device_preference="cpu")
    await encoder.load()

    FakeModel.__call__ = lambda self, **kwargs: (
        loop.call_soon_threadsafe(aio_event.set),
        entered.wait(),
        SimpleNamespace(last_hidden_state=torch.randn(1, 197, 384)),
    )[-1]

    image = Image.new("RGB", (224, 224), color=(128, 128, 128))
    encode_task = asyncio.create_task(encoder.encode(image))
    try:
        await asyncio.wait_for(aio_event.wait(), timeout=5)

        encode_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await encode_task

        unload_task = asyncio.create_task(asyncio.wait_for(encoder.unload(), timeout=5))
        await asyncio.sleep(0.1)
        assert not unload_task.done()
        assert encoder.loaded
        assert encoder._gate.inflight == 1
    finally:
        entered.set()

    assert unload_task is not None
    await asyncio.wait_for(unload_task, timeout=5)
    assert not encoder.loaded


@pytest.mark.asyncio
async def test_internvideo_next_double_cancel_does_not_leak_inflight(monkeypatch):
    """A twice-cancelled in-flight encode_clip releases the in-flight count."""

    def fake_loader(**kwargs):
        return object()

    def fake_processor(*args, **kwargs):
        return {"pixel_values": torch.zeros(1, 16, 3, 224, 224)}

    monkeypatch.setattr(
        "kaine.modules.topos.internvideo_next_loader.load_internvideo_next",
        fake_loader,
    )
    monkeypatch.setattr(
        "kaine.modules.topos.encoder._load_videomae_processor",
        fake_processor,
    )

    encoder = InternVideoNextEncoder(device_preference="cpu", clip_len=16)

    # Non-blocking probe for load().
    encoder._forward_clip = lambda frames, **kwargs: [1.0] * 768
    await encoder.load()

    loop = asyncio.get_running_loop()
    entered = threading.Event()
    aio_event = asyncio.Event()

    def blocking_forward(frames, **kwargs):
        loop.call_soon_threadsafe(aio_event.set)
        entered.wait()
        return [1.0] * 768

    encoder._forward_clip = blocking_forward

    frames = [Image.new("RGB", (224, 224), color=(128, 128, 128)) for _ in range(16)]
    encode_task = asyncio.create_task(encoder.encode_clip(frames))
    try:
        await asyncio.wait_for(aio_event.wait(), timeout=5)

        lock = encoder._get_lock()
        await lock.acquire()
        try:
            encode_task.cancel()
            await asyncio.sleep(0)
            encode_task.cancel()
            await asyncio.sleep(0)
        finally:
            lock.release()
    finally:
        entered.set()

    with pytest.raises(asyncio.CancelledError):
        await encode_task

    await asyncio.wait_for(encoder.unload(), timeout=2)
    assert encoder._gate.inflight == 0


def test_internvideo_loader_uses_safetensors(tmp_path, monkeypatch):
    """The InternVideo-Next offline loader requests safetensors for weights only."""
    from kaine.modules.topos.internvideo_next_loader import load_internvideo_next

    wdir = tmp_path / "internvideo_next"
    wdir.mkdir()
    (wdir / WEIGHTS_FILENAME).write_text("stub")

    config_calls: list[dict] = []
    model_kwargs: dict = {}

    class FakeConfig:
        @classmethod
        def from_pretrained(cls, path, **kwargs):
            config_calls.append({"path": path, "kwargs": kwargs})
            return SimpleNamespace(
                model_config={
                    "use_flash_attn": True,
                    "use_fused_rmsnorm": True,
                    "use_fused_mlp": True,
                }
            )

    class FakeModel:
        def eval(self):
            return self

        def parameters(self):
            return iter(())

        def to(self, device):
            return self

    class FakeModelCls:
        @classmethod
        def from_pretrained(cls, path, **kwargs):
            model_kwargs.update(kwargs)
            return FakeModel()

    load_internvideo_next(
        weights_dir=wdir,
        device="cpu",
        _classes=(FakeConfig, FakeModelCls),
    )

    assert model_kwargs.get("use_safetensors") is True
    assert config_calls[0]["kwargs"].get("use_safetensors") is None
