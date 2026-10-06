# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for reversible unload and mapped weights for text embedders."""

from __future__ import annotations

import asyncio
import gc
import json
import math
import threading
import weakref
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from kaine.text_embedding import SharedEmbedder
from kaine.text_embedding_numpy import (
    NumpyMiniLMEmbedder,
    bert_forward,
    read_safetensors,
    weights_residency,
)
from tests.test_text_embedding_numpy import _make_tiny_bert_dir, _write_safetensors


@pytest.fixture
def bert_dir(tmp_path: Path) -> Path:
    return _make_tiny_bert_dir(tmp_path)


def test_read_safetensors_mapped_and_private(tmp_path: Path) -> None:
    f32 = np.arange(4, dtype=np.float32).reshape(2, 2)
    f16 = np.arange(4, dtype=np.float16).reshape(2, 2)
    i64 = np.arange(4, dtype=np.int64).reshape(2, 2)
    i32 = np.arange(4, dtype=np.int32).reshape(2, 2)

    path = tmp_path / "mixed.safetensors"
    _write_safetensors(path, {"f32": f32, "f16": f16, "i64": i64, "i32": i32})

    tensors = read_safetensors(path)

    assert tensors["f32"].dtype == np.float32
    assert tensors["f32"].flags.writeable is False
    np.testing.assert_array_equal(tensors["f32"], f32)

    assert tensors["f16"].dtype == np.float32
    assert tensors["f16"].flags.writeable is True
    np.testing.assert_array_equal(tensors["f16"], f16.astype(np.float32))

    assert tensors["i64"].dtype == np.int64
    assert tensors["i64"].flags.writeable is False
    assert tensors["i32"].dtype == np.int32
    assert tensors["i32"].flags.writeable is False

    residency = weights_residency(tensors)
    assert residency["private_bytes"] == tensors["f16"].nbytes
    assert residency["mapped_bytes"] == (
        tensors["f32"].nbytes + tensors["i64"].nbytes + tensors["i32"].nbytes
    )


def test_read_safetensors_truncated_errors(tmp_path: Path) -> None:
    empty = tmp_path / "empty.safetensors"
    empty.write_bytes(b"")
    with pytest.raises(ValueError, match="safetensors file truncated"):
        read_safetensors(empty)

    small = tmp_path / "small.safetensors"
    small.write_bytes(b"12345")
    with pytest.raises(ValueError, match="safetensors file truncated"):
        read_safetensors(small)


def test_embedder_unload_and_reload(bert_dir: Path) -> None:
    async def main() -> None:
        embedder = NumpyMiniLMEmbedder(model_path=str(bert_dir))
        assert not embedder.loaded

        vec1 = await asyncio.wait_for(embedder.encode("hello world"), 5)
        residency1 = embedder.weights_residency
        assert residency1["mapped_bytes"] > 0

        await asyncio.wait_for(embedder.unload(), 5)
        assert not embedder.loaded
        assert embedder.weights_residency == {}

        vec2 = await asyncio.wait_for(embedder.encode("hello world"), 5)
        assert vec1 == vec2
        assert embedder.loaded

    asyncio.run(main())


def test_embedder_encode_loads_if_needed(bert_dir: Path) -> None:
    async def main() -> None:
        embedder = NumpyMiniLMEmbedder(model_path=str(bert_dir))
        assert not embedder.loaded
        vec = await asyncio.wait_for(embedder.encode("hello world"), 5)
        assert len(vec) == embedder.latent_dim
        assert embedder.loaded

    asyncio.run(main())


def test_embedder_unload_waits_for_inflight(
    bert_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import kaine.text_embedding_numpy as ten_mod

    original_forward = ten_mod.bert_forward

    async def main() -> None:
        embedder = NumpyMiniLMEmbedder(model_path=str(bert_dir))
        loop = asyncio.get_running_loop()
        blocked_async = asyncio.Event()
        release_thread = threading.Event()

        def blocked_forward(
            weights: dict[str, np.ndarray],
            config: dict[str, Any],
            input_ids: np.ndarray,
            attention_mask: np.ndarray,
        ) -> np.ndarray:
            loop.call_soon_threadsafe(blocked_async.set)
            release_thread.wait()
            return original_forward(weights, config, input_ids, attention_mask)

        monkeypatch.setattr(ten_mod, "bert_forward", blocked_forward)

        encode_task = asyncio.create_task(embedder.encode_batch(["hello world"]))
        await asyncio.wait_for(blocked_async.wait(), 5)

        unload_task = asyncio.create_task(embedder.unload())
        await asyncio.sleep(0)
        assert not unload_task.done()

        release_thread.set()
        result = await asyncio.wait_for(encode_task, 5)
        await asyncio.wait_for(unload_task, 5)

        assert len(result) == 1
        assert len(result[0]) == embedder.latent_dim
        norm = math.sqrt(sum(x * x for x in result[0]))
        assert abs(norm - 1.0) < 1e-6

    asyncio.run(main())


def test_bert_forward_readonly_same_as_copy(bert_dir: Path) -> None:
    config = json.loads((bert_dir / "config.json").read_text())
    weights = read_safetensors(bert_dir / "model.safetensors")

    for arr in weights.values():
        assert arr.flags.writeable is False

    copies = {k: np.array(v) for k, v in weights.items()}
    input_ids = np.array([[1, 2, 3, 0]], dtype=np.int64)
    attention_mask = np.array([[1, 1, 1, 0]], dtype=np.int64)

    out_mapped = bert_forward(weights, config, input_ids, attention_mask)
    out_copied = bert_forward(copies, config, input_ids, attention_mask)

    np.testing.assert_array_equal(out_mapped, out_copied)


def test_shared_embedder_unload_and_reload(bert_dir: Path) -> None:
    async def main() -> None:
        inner = NumpyMiniLMEmbedder(model_path=str(bert_dir))
        shared = SharedEmbedder(inner)

        vec1 = await asyncio.wait_for(shared.encode("hello world"), 5)
        assert shared.loaded

        await asyncio.wait_for(shared.unload(), 5)
        assert not inner.loaded
        assert not shared.loaded

        vec2 = await asyncio.wait_for(shared.encode("hello world"), 5)
        assert vec1 == vec2
        assert shared.loaded

    asyncio.run(main())


def test_unload_collects_weight_refs(bert_dir: Path) -> None:
    async def main() -> None:
        embedder = NumpyMiniLMEmbedder(model_path=str(bert_dir))
        await asyncio.wait_for(embedder.load(), 5)

        weight = list(embedder._weights.values())[0]
        ref = weakref.ref(weight)
        del weight

        await asyncio.wait_for(embedder.unload(), 5)
        gc.collect()

        assert ref() is None

    asyncio.run(main())


def test_numpy_unload_in_gap_returns_consistent_vector(bert_dir: Path) -> None:
    async def main() -> None:
        embedder = NumpyMiniLMEmbedder(model_path=str(bert_dir))

        expected = await asyncio.wait_for(embedder.encode_batch(["hello world"]), 5)

        original_ensure_loaded = embedder.ensure_loaded

        async def wrapped() -> None:
            await original_ensure_loaded()
            await embedder.unload()

        embedder.ensure_loaded = wrapped

        await asyncio.wait_for(embedder.ensure_loaded(), 5)
        vec = await asyncio.wait_for(embedder.encode_batch(["hello world"]), 5)

        assert vec == expected

    asyncio.run(main())


def test_numpy_empty_batch_does_not_load(bert_dir: Path) -> None:
    async def main() -> None:
        embedder = NumpyMiniLMEmbedder(model_path=str(bert_dir))
        assert not embedder.loaded
        result = await asyncio.wait_for(embedder.encode_batch([]), 5)
        assert result == []
        assert not embedder.loaded

    asyncio.run(main())


def test_torch_unload_in_gap_returns_ones(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import types

    fake_mod = types.ModuleType("sentence_transformers")

    class FakeSentenceTransformer:
        def __init__(self, model_id: str, device: str = "cpu") -> None:
            self.model_id = model_id
            self.device = device

        def encode(self, x, *, convert_to_numpy: bool = True, show_progress_bar: bool = False):
            import numpy as np

            if isinstance(x, str):
                return np.ones(4)
            return np.ones((len(x), 4))

        def get_sentence_embedding_dimension(self) -> int:
            return 4

    fake_mod.SentenceTransformer = FakeSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_mod)
    monkeypatch.setattr("kaine.hardware.resolve_device", lambda _pref: "cpu")

    async def main() -> None:
        from kaine.text_embedding import SentenceTransformerTextEmbedder

        embedder = SentenceTransformerTextEmbedder(model_id="fake/model")

        original_ensure_loaded = embedder.ensure_loaded

        async def wrapped() -> None:
            await original_ensure_loaded()
            await embedder.unload()

        embedder.ensure_loaded = wrapped

        await asyncio.wait_for(embedder.ensure_loaded(), 5)
        vec = await asyncio.wait_for(embedder.encode("x"), 5)
        assert vec == [1.0, 1.0, 1.0, 1.0]

        await asyncio.wait_for(embedder.ensure_loaded(), 5)
        batch = await asyncio.wait_for(embedder.encode_batch(["x"]), 5)
        assert batch == [[1.0, 1.0, 1.0, 1.0]]

    asyncio.run(main())


def test_numpy_double_cancel_does_not_leak_inflight(
    bert_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import kaine.text_embedding_numpy as ten_mod

    original_forward = ten_mod.bert_forward

    async def main() -> None:
        embedder = NumpyMiniLMEmbedder(model_path=str(bert_dir))
        loop = asyncio.get_running_loop()
        in_worker = asyncio.Event()
        release_thread = threading.Event()

        def blocked_forward(
            weights: dict[str, np.ndarray],
            config: dict[str, Any],
            input_ids: np.ndarray,
            attention_mask: np.ndarray,
        ) -> np.ndarray:
            loop.call_soon_threadsafe(in_worker.set)
            release_thread.wait()
            return original_forward(weights, config, input_ids, attention_mask)

        monkeypatch.setattr(ten_mod, "bert_forward", blocked_forward)

        encode_task = asyncio.create_task(embedder.encode("hello world"))
        try:
            await asyncio.wait_for(in_worker.wait(), 5)
            await embedder._load_lock.acquire()
            encode_task.cancel()
            await asyncio.sleep(0)
            encode_task.cancel()
            await asyncio.sleep(0)
            embedder._load_lock.release()
            release_thread.set()
            try:
                await asyncio.wait_for(encode_task, 2)
            except asyncio.CancelledError:
                pass
            await asyncio.wait_for(embedder.unload(), 2)
            assert embedder._inflight == 0
        finally:
            release_thread.set()

    asyncio.run(main())


def test_sentence_double_cancel_does_not_leak_inflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    import types

    loop_ref: asyncio.AbstractEventLoop | None = None
    in_worker: asyncio.Event | None = None
    release_thread: threading.Event | None = None

    fake_mod = types.ModuleType("sentence_transformers")

    class FakeSentenceTransformer:
        def __init__(self, model_id: str, device: str = "cpu") -> None:
            self.model_id = model_id
            self.device = device

        def encode(self, x, *, convert_to_numpy: bool = True, show_progress_bar: bool = False):
            import numpy as np

            if loop_ref is not None and in_worker is not None:
                loop_ref.call_soon_threadsafe(in_worker.set())
            if release_thread is not None:
                release_thread.wait()
            if isinstance(x, str):
                return np.ones(4)
            return np.ones((len(x), 4))

        def get_sentence_embedding_dimension(self) -> int:
            return 4

    fake_mod.SentenceTransformer = FakeSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_mod)
    monkeypatch.setattr("kaine.hardware.resolve_device", lambda _pref: "cpu")

    async def main() -> None:
        nonlocal loop_ref, in_worker, release_thread
        from kaine.text_embedding import SentenceTransformerTextEmbedder

        loop_ref = asyncio.get_running_loop()
        in_worker = asyncio.Event()
        release_thread = threading.Event()

        embedder = SentenceTransformerTextEmbedder(model_id="fake/model")
        encode_task = asyncio.create_task(embedder.encode("hello world"))
        try:
            await asyncio.wait_for(in_worker.wait(), 5)
            await embedder._load_lock.acquire()
            encode_task.cancel()
            await asyncio.sleep(0)
            encode_task.cancel()
            await asyncio.sleep(0)
            embedder._load_lock.release()
            release_thread.set()
            try:
                await asyncio.wait_for(encode_task, 2)
            except asyncio.CancelledError:
                pass
            await asyncio.wait_for(embedder.unload(), 2)
            assert embedder._inflight == 0
        finally:
            if release_thread is not None:
                release_thread.set()

    asyncio.run(main())
