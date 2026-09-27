# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the NumPy-only BERT-style text embedder."""
# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
import json
import math
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

import kaine.text_embedding_numpy
from kaine.text_embedding_numpy import (
    NumpyMiniLMEmbedder,
    WordPieceTokenizer,
    _erf_numpy,
    bert_forward,
    mean_pool_normalize,
    read_safetensors,
    resolve_model_dir,
)


def _write_safetensors(path: Path, tensors: dict[str, np.ndarray]) -> None:
    header: dict[str, Any] = {}
    raw = b""
    offset = 0
    for name, arr in tensors.items():
        if arr.dtype == np.float32:
            dtype_key = "F32"
        elif arr.dtype == np.float16:
            dtype_key = "F16"
        elif arr.dtype == np.int64:
            dtype_key = "I64"
        elif arr.dtype == np.int32:
            dtype_key = "I32"
        else:
            raise ValueError(f"unsupported dtype {arr.dtype} for safetensors test helper")
        itemsize = arr.dtype.itemsize
        size = int(np.prod(arr.shape, dtype=np.int64)) * itemsize
        header[name] = {
            "dtype": dtype_key,
            "shape": list(arr.shape),
            "data_offsets": [offset, offset + size],
        }
        raw += arr.tobytes()
        offset += size
    header_bytes = json.dumps(header).encode("utf-8")
    path.write_bytes(struct.pack("<Q", len(header_bytes)) + header_bytes + raw)


def test_read_safetensors_roundtrip(tmp_path: Path) -> None:
    f32 = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
    f16 = np.array([0.5, -1.5, 2.5], dtype=np.float16)
    i64 = np.arange(5, dtype=np.int64).reshape(1, 5)
    scalar = np.array(3.14159, dtype=np.float32)

    path = tmp_path / "model.safetensors"
    _write_safetensors(path, {"a": f32, "b": f16, "c": i64, "s": scalar})

    out = read_safetensors(path)
    assert np.allclose(out["a"], f32)
    assert out["a"].dtype == np.float32
    assert np.allclose(out["b"], f16.astype(np.float32))
    assert out["b"].dtype == np.float32
    assert np.array_equal(out["c"], i64)
    assert out["c"].dtype == np.int64
    assert out["c"].shape == (1, 5)
    assert np.allclose(out["s"], scalar)
    assert out["s"].dtype == np.float32
    assert out["s"].shape == ()

    truncated = path.read_bytes()[:20]
    trunc_path = tmp_path / "trunc.safetensors"
    trunc_path.write_bytes(truncated)
    with pytest.raises(ValueError):
        read_safetensors(trunc_path)

    bf16_header = json.dumps(
        {"c": {"dtype": "BF16", "shape": [1], "data_offsets": [0, 2]}}
    ).encode("utf-8")
    bad_path = tmp_path / "bad.safetensors"
    bad_path.write_bytes(struct.pack("<Q", len(bf16_header)) + bf16_header + b"\x00\x00")
    with pytest.raises(ValueError):
        read_safetensors(bad_path)


def test_mean_pool_normalize_ignores_padding() -> None:
    hidden = np.zeros((1, 3, 4), dtype=np.float32)
    hidden[0, 0] = [1.0, 2.0, 3.0, 4.0]
    hidden[0, 1] = [5.0, 6.0, 7.0, 8.0]
    hidden[0, 2] = [1e6, 1e6, 1e6, 1e6]
    mask = np.array([[1, 1, 0]], dtype=np.int64)

    result = mean_pool_normalize(hidden, mask)
    result_arr = np.asarray(result, dtype=np.float32).reshape(-1)

    expected = np.mean([hidden[0, 0], hidden[0, 1]], axis=0)
    expected = expected / np.linalg.norm(expected)

    assert np.allclose(result_arr, expected, atol=1e-6)
    assert abs(float(np.linalg.norm(result_arr)) - 1.0) < 1e-6


def _build_tiny_bert_vocab() -> list[str]:
    specials = (
        ["[PAD]"]
        + [f"[unused{i}]" for i in range(5)]
        + ["[UNK]", "[CLS]", "[SEP]", "[MASK]"]
    )
    words = [
        "hello",
        "London",
        "world",
        "the",
        "a",
        "is",
        "test",
        "this",
        "that",
        "and",
        "i",
        "am",
        "here",
        "my",
        "name",
        "good",
        "bad",
        "day",
        "night",
        "of",
        "to",
        "in",
        "for",
        "on",
        "it",
        "you",
        "we",
        "are",
        "was",
        "were",
        "be",
    ]
    cont = ["##ing", "##ed", "##s", "##ly", "##er", "##est", "##tion", "##ness", "##ment", "##ful"]
    return specials + words + cont


def _make_tiny_bert_dir(tmp_path: Path) -> Path:
    rng = np.random.default_rng(42)
    vocab = _build_tiny_bert_vocab()
    hidden = 8
    heads = 2
    layers = 2
    intermediate = 16
    positions = 32
    type_vocab = 2
    vocab_size = len(vocab)

    weights: dict[str, np.ndarray] = {}
    weights["embeddings.word_embeddings.weight"] = rng.normal(0, 0.02, (vocab_size, hidden)).astype(np.float32)
    weights["embeddings.position_embeddings.weight"] = rng.normal(0, 0.02, (positions, hidden)).astype(np.float32)
    weights["embeddings.token_type_embeddings.weight"] = rng.normal(0, 0.02, (type_vocab, hidden)).astype(np.float32)
    weights["embeddings.LayerNorm.weight"] = np.ones(hidden, dtype=np.float32)
    weights["embeddings.LayerNorm.bias"] = np.zeros(hidden, dtype=np.float32)

    for layer in range(layers):
        pfx = f"encoder.layer.{layer}"
        weights[f"{pfx}.attention.self.query.weight"] = rng.normal(0, 0.02, (hidden, hidden)).astype(np.float32)
        weights[f"{pfx}.attention.self.query.bias"] = np.zeros(hidden, dtype=np.float32)
        weights[f"{pfx}.attention.self.key.weight"] = rng.normal(0, 0.02, (hidden, hidden)).astype(np.float32)
        weights[f"{pfx}.attention.self.key.bias"] = np.zeros(hidden, dtype=np.float32)
        weights[f"{pfx}.attention.self.value.weight"] = rng.normal(0, 0.02, (hidden, hidden)).astype(np.float32)
        weights[f"{pfx}.attention.self.value.bias"] = np.zeros(hidden, dtype=np.float32)
        weights[f"{pfx}.attention.output.dense.weight"] = rng.normal(0, 0.02, (hidden, hidden)).astype(np.float32)
        weights[f"{pfx}.attention.output.dense.bias"] = np.zeros(hidden, dtype=np.float32)
        weights[f"{pfx}.attention.output.LayerNorm.weight"] = np.ones(hidden, dtype=np.float32)
        weights[f"{pfx}.attention.output.LayerNorm.bias"] = np.zeros(hidden, dtype=np.float32)
        weights[f"{pfx}.intermediate.dense.weight"] = rng.normal(0, 0.02, (intermediate, hidden)).astype(np.float32)
        weights[f"{pfx}.intermediate.dense.bias"] = np.zeros(intermediate, dtype=np.float32)
        weights[f"{pfx}.output.dense.weight"] = rng.normal(0, 0.02, (hidden, intermediate)).astype(np.float32)
        weights[f"{pfx}.output.dense.bias"] = np.zeros(hidden, dtype=np.float32)
        weights[f"{pfx}.output.LayerNorm.weight"] = np.ones(hidden, dtype=np.float32)
        weights[f"{pfx}.output.LayerNorm.bias"] = np.zeros(hidden, dtype=np.float32)

    model_dir = tmp_path / "tiny_bert"
    model_dir.mkdir()
    _write_safetensors(model_dir / "model.safetensors", weights)

    config = {
        "model_type": "bert",
        "hidden_act": "gelu",
        "hidden_size": hidden,
        "num_hidden_layers": layers,
        "num_attention_heads": heads,
        "intermediate_size": intermediate,
        "layer_norm_eps": 1e-12,
        "max_position_embeddings": positions,
        "type_vocab_size": type_vocab,
        "vocab_size": vocab_size,
    }
    (model_dir / "config.json").write_text(json.dumps(config))

    (model_dir / "vocab.txt").write_text("\n".join(vocab))

    tok_cfg = {
        "do_lower_case": True,
        "tokenize_chinese_chars": True,
        "special_tokens_map": {
            "unk_token": "[PAD]",
            "cls_token": "[CLS]",
            "sep_token": "[SEP]",
            "mask_token": "[MASK]",
        },
    }
    (model_dir / "tokenizer_config.json").write_text(json.dumps(tok_cfg))

    modules = [
        {
            "name": "0",
            "type": "sentence_transformers.models.Transformer",
            "path": "0_Transformer",
        },
        {
            "name": "1",
            "type": "sentence_transformers.models.Pooling",
            "path": "1_Pooling",
        },
        {
            "name": "2",
            "type": "sentence_transformers.models.Normalize",
            "path": "2_Normalize",
        },
    ]
    (model_dir / "modules.json").write_text(json.dumps(modules))

    (model_dir / "1_Pooling").mkdir()
    pool_cfg = {
        "pooling_mode_mean_tokens": True,
        "pooling_mode_cls_token": False,
        "pooling_mode_max_tokens": False,
        "pooling_mode_mean_sqrt_len_tokens": False,
        "pooling_mode_lasttoken": False,
        "pooling_mode_whole_word_tokens": False,
        "pooling_mode_weightedmean_tokens": False,
    }
    (model_dir / "1_Pooling" / "config.json").write_text(json.dumps(pool_cfg))

    sbc = {"max_seq_length": 16}
    (model_dir / "sentence_bert_config.json").write_text(json.dumps(sbc))

    return model_dir


@pytest.fixture
def tiny_bert_dir(tmp_path: Path) -> Path:
    return _make_tiny_bert_dir(tmp_path)


def test_tiny_bert_load_and_encode(tiny_bert_dir: Path) -> None:
    embedder = NumpyMiniLMEmbedder(model_path=str(tiny_bert_dir))
    assert embedder.latent_dim == 8
    assert embedder.model_id == "sentence-transformers/all-MiniLM-L6-v2"

    asyncio.run(embedder.load())

    assert embedder.latent_dim == 8

    vec = asyncio.run(embedder.encode("hello world"))
    assert len(vec) == 8
    norm = math.sqrt(sum(v * v for v in vec))
    assert abs(norm - 1.0) < 1e-6

    texts = ["hello world", "this is a longer test sentence"]
    batch = asyncio.run(embedder.encode_batch(texts))
    assert len(batch) == 2
    assert all(len(v) == 8 for v in batch)
    for a, b in zip(batch[0], vec):
        assert abs(a - b) < 1e-6

    fresh = NumpyMiniLMEmbedder(model_path=str(tiny_bert_dir))
    with pytest.raises(RuntimeError):
        asyncio.run(fresh.encode("hello world"))


def test_tokenizer_config_do_lower_case_false_preserves_cased(tiny_bert_dir: Path) -> None:
    cased_dir = tiny_bert_dir.parent / "tiny_bert_cased"
    shutil.copytree(tiny_bert_dir, cased_dir)
    tok_cfg = {
        "do_lower_case": False,
        "tokenize_chinese_chars": True,
        "special_tokens_map": {
            "unk_token": "[PAD]",
            "cls_token": "[CLS]",
            "sep_token": "[SEP]",
            "mask_token": "[MASK]",
        },
    }
    (cased_dir / "tokenizer_config.json").write_text(json.dumps(tok_cfg))
    embedder = NumpyMiniLMEmbedder(model_path=str(cased_dir))
    asyncio.run(embedder.load())
    ids = embedder._tokenizer.encode("London")
    vocab = [line.strip() for line in (cased_dir / "vocab.txt").read_text().splitlines()]
    assert ids == [vocab.index("[CLS]"), vocab.index("London"), vocab.index("[SEP]")]


def test_encode_batch_empty_returns_empty(tiny_bert_dir: Path) -> None:
    embedder = NumpyMiniLMEmbedder(model_path=str(tiny_bert_dir))
    asyncio.run(embedder.load())
    assert asyncio.run(embedder.encode_batch([])) == []


def test_tiny_bert_invalid_pooling(tiny_bert_dir: Path) -> None:
    cls_dir = tiny_bert_dir.parent / "tiny_bert_cls"
    cls_dir.mkdir()
    for p in tiny_bert_dir.iterdir():
        if p.is_dir():
            import shutil

            shutil.copytree(p, cls_dir / p.name)
        else:
            import shutil

            shutil.copy2(p, cls_dir / p.name)

    pool_cfg = {
        "pooling_mode_mean_tokens": False,
        "pooling_mode_cls_token": True,
        "pooling_mode_max_tokens": False,
        "pooling_mode_mean_sqrt_len_tokens": False,
        "pooling_mode_lasttoken": False,
        "pooling_mode_whole_word_tokens": False,
        "pooling_mode_weightedmean_tokens": False,
    }
    (cls_dir / "1_Pooling" / "config.json").write_text(json.dumps(pool_cfg))

    embedder = NumpyMiniLMEmbedder(model_path=str(cls_dir))
    with pytest.raises(ValueError):
        asyncio.run(embedder.load())

    no_norm_dir = tiny_bert_dir.parent / "tiny_bert_no_norm"
    no_norm_dir.mkdir()
    for p in tiny_bert_dir.iterdir():
        if p.is_dir():
            import shutil

            shutil.copytree(p, no_norm_dir / p.name)
        else:
            import shutil

            shutil.copy2(p, no_norm_dir / p.name)

    modules = [
        {
            "name": "0",
            "type": "sentence_transformers.models.Transformer",
            "path": "0_Transformer",
        },
        {
            "name": "1",
            "type": "sentence_transformers.models.Pooling",
            "path": "1_Pooling",
        },
    ]
    (no_norm_dir / "modules.json").write_text(json.dumps(modules))
    embedder2 = NumpyMiniLMEmbedder(model_path=str(no_norm_dir))
    with pytest.raises(ValueError):
        asyncio.run(embedder2.load())


def test_load_refuses_unsupported_model_type(tiny_bert_dir: Path) -> None:
    bad_dir = tiny_bert_dir.parent / "tiny_bert_roberta"
    shutil.copytree(tiny_bert_dir, bad_dir)
    cfg = json.loads((bad_dir / "config.json").read_text())
    cfg["model_type"] = "roberta"
    (bad_dir / "config.json").write_text(json.dumps(cfg))
    embedder = NumpyMiniLMEmbedder(model_path=str(bad_dir))
    with pytest.raises(ValueError, match="model_type"):
        asyncio.run(embedder.load())


def test_load_refuses_unsupported_hidden_act(tiny_bert_dir: Path) -> None:
    bad_dir = tiny_bert_dir.parent / "tiny_bert_relu"
    shutil.copytree(tiny_bert_dir, bad_dir)
    cfg = json.loads((bad_dir / "config.json").read_text())
    cfg["hidden_act"] = "relu"
    (bad_dir / "config.json").write_text(json.dumps(cfg))
    embedder = NumpyMiniLMEmbedder(model_path=str(bad_dir))
    with pytest.raises(ValueError, match="hidden_act"):
        asyncio.run(embedder.load())


def test_load_refuses_relative_position_embedding(tiny_bert_dir: Path) -> None:
    bad_dir = tiny_bert_dir.parent / "tiny_bert_relative"
    shutil.copytree(tiny_bert_dir, bad_dir)
    cfg = json.loads((bad_dir / "config.json").read_text())
    cfg["position_embedding_type"] = "relative_key"
    (bad_dir / "config.json").write_text(json.dumps(cfg))
    embedder = NumpyMiniLMEmbedder(model_path=str(bad_dir))
    with pytest.raises(ValueError, match="position_embedding_type"):
        asyncio.run(embedder.load())


def test_load_refuses_missing_layer_weight(tiny_bert_dir: Path) -> None:
    bad_dir = tiny_bert_dir.parent / "tiny_bert_missing"
    shutil.copytree(tiny_bert_dir, bad_dir)
    weights = read_safetensors(bad_dir / "model.safetensors")
    del weights["encoder.layer.0.attention.self.query.weight"]
    _write_safetensors(bad_dir / "model.safetensors", weights)
    embedder = NumpyMiniLMEmbedder(model_path=str(bad_dir))
    with pytest.raises(ValueError, match="encoder.layer.0.attention.self.query.weight"):
        asyncio.run(embedder.load())


def test_load_refuses_misshaped_weight(tiny_bert_dir: Path) -> None:
    bad_dir = tiny_bert_dir.parent / "tiny_bert_shape"
    shutil.copytree(tiny_bert_dir, bad_dir)
    weights = read_safetensors(bad_dir / "model.safetensors")
    w = weights["encoder.layer.0.attention.self.query.weight"]
    weights["encoder.layer.0.attention.self.query.weight"] = w[: w.shape[0] // 2]
    _write_safetensors(bad_dir / "model.safetensors", weights)
    embedder = NumpyMiniLMEmbedder(model_path=str(bad_dir))
    with pytest.raises(ValueError, match="shape"):
        asyncio.run(embedder.load())


def test_bert_forward_reference(tiny_bert_dir: Path) -> None:
    weights = read_safetensors(tiny_bert_dir / "model.safetensors")
    full_cfg = json.loads((tiny_bert_dir / "config.json").read_text())
    cfg = {**full_cfg, "num_hidden_layers": 1}

    vocab = [line.strip() for line in (tiny_bert_dir / "vocab.txt").read_text().splitlines()]
    vocab_map = {t: i for i, t in enumerate(vocab)}
    tokenizer = WordPieceTokenizer(vocab_map, max_length=16)

    text = "hello world"
    ids = tokenizer.encode(text)
    seq = len(ids)
    input_ids = np.array([ids], dtype=np.int64)
    mask = np.ones((1, seq), dtype=np.int64)

    hidden = bert_forward(weights, cfg, input_ids, mask)
    hidden = hidden.astype(np.float32)

    # Independent one-layer re-implementation
    batch, s, hidden_size = hidden.shape
    num_heads = cfg["num_attention_heads"]
    head_dim = hidden_size // num_heads
    eps = cfg["layer_norm_eps"]

    word_w = weights["embeddings.word_embeddings.weight"]
    pos_w = weights["embeddings.position_embeddings.weight"]
    type_w = weights["embeddings.token_type_embeddings.weight"]
    ln_g = weights["embeddings.LayerNorm.weight"]
    ln_b = weights["embeddings.LayerNorm.bias"]

    x = word_w[input_ids[0]] + pos_w[np.arange(seq)] + type_w[0]
    mean = x.mean(axis=-1, keepdims=True)
    var = x.var(axis=-1, keepdims=True, ddof=0)
    x_ref = ((x - mean) / np.sqrt(var + eps)) * ln_g + ln_b

    def linear(xv: np.ndarray, W: np.ndarray, b: np.ndarray) -> np.ndarray:
        return xv @ W.T + b

    q = linear(x_ref, weights["encoder.layer.0.attention.self.query.weight"], weights["encoder.layer.0.attention.self.query.bias"])
    k = linear(x_ref, weights["encoder.layer.0.attention.self.key.weight"], weights["encoder.layer.0.attention.self.key.bias"])
    v = linear(x_ref, weights["encoder.layer.0.attention.self.value.weight"], weights["encoder.layer.0.attention.self.value.bias"])

    q_h = q.reshape(s, num_heads, head_dim).transpose(1, 0, 2)
    k_h = k.reshape(s, num_heads, head_dim).transpose(1, 0, 2)
    v_h = v.reshape(s, num_heads, head_dim).transpose(1, 0, 2)

    scores = np.stack(
        [
            (q_h[h] @ k_h[h].T) / math.sqrt(head_dim)
            for h in range(num_heads)
        ],
        axis=0,
    )
    scores = np.where(mask[0, None, None, :], scores, np.finfo(np.float32).min)

    attn = np.empty_like(scores)
    for h in range(num_heads):
        for i in range(s):
            row = scores[h, i]
            row = row - row.max()
            e = np.exp(row)
            attn[h, i] = e / e.sum()

    context_h = np.stack(
        [attn[h] @ v_h[h] for h in range(num_heads)],
        axis=0,
    )
    context = context_h.transpose(1, 0, 2).reshape(s, hidden_size)
    out = linear(context, weights["encoder.layer.0.attention.output.dense.weight"], weights["encoder.layer.0.attention.output.dense.bias"])
    mean = (x_ref + out).mean(axis=-1, keepdims=True)
    var = (x_ref + out).var(axis=-1, keepdims=True, ddof=0)
    x_ref = ((x_ref + out - mean) / np.sqrt(var + eps)) * weights["encoder.layer.0.attention.output.LayerNorm.weight"] + weights["encoder.layer.0.attention.output.LayerNorm.bias"]

    h_ffn = linear(x_ref, weights["encoder.layer.0.intermediate.dense.weight"], weights["encoder.layer.0.intermediate.dense.bias"])

    def gelu_ref(xv: np.ndarray) -> np.ndarray:
        from scipy.special import erf

        return (xv * 0.5 * (1.0 + erf(xv / np.sqrt(2.0)))).astype(np.float32)

    h_ffn = gelu_ref(h_ffn)
    out2 = linear(h_ffn, weights["encoder.layer.0.output.dense.weight"], weights["encoder.layer.0.output.dense.bias"])
    mean = (x_ref + out2).mean(axis=-1, keepdims=True)
    var = (x_ref + out2).var(axis=-1, keepdims=True, ddof=0)
    x_ref = ((x_ref + out2 - mean) / np.sqrt(var + eps)) * weights["encoder.layer.0.output.LayerNorm.weight"] + weights["encoder.layer.0.output.LayerNorm.bias"]

    assert np.allclose(hidden[0], x_ref, atol=1e-5)


def test_no_torch_subprocess(tiny_bert_dir: Path) -> None:
    script = f'''
import sys
BLOCKED = {{"torch", "transformers", "sentence_transformers", "safetensors", "huggingface_hub"}}

class BlockFinder:
    def find_spec(self, name, path, target=None):
        root = name.split(".")[0]
        if root in BLOCKED:
            raise ImportError("blocked import: " + name)
    def find_module(self, name, path=None):
        root = name.split(".")[0]
        if root in BLOCKED:
            raise ImportError("blocked import: " + name)

sys.meta_path.insert(0, BlockFinder())

from kaine.text_embedding_numpy import NumpyMiniLMEmbedder
import asyncio

async def main():
    e = NumpyMiniLMEmbedder(model_path={str(tiny_bert_dir)!r})
    await e.load()
    v = await e.encode("hello world")
    print(",".join(str(float(x)) for x in v))

asyncio.run(main())
'''
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert result.returncode == 0, result.stderr
    values = [float(x) for x in result.stdout.strip().split(",") if x]
    assert len(values) == 8


def test_resolve_model_dir(tmp_path: Path) -> None:
    # HF_HUB_CACHE beats HF_HOME
    hf_hub_cache = tmp_path / "hf_hub_cache"
    hf_home = tmp_path / "hf_home"
    for root in (hf_hub_cache, hf_home):
        repo = root / "hub" / "models--org--name"
        (repo / "refs").mkdir(parents=True)
        (repo / "refs" / "main").write_text("abc123\n")
        snap = repo / "snapshots" / "abc123"
        snap.mkdir(parents=True)

    env = {
        "HF_HUB_CACHE": str(hf_hub_cache / "hub"),
        "HF_HOME": str(hf_home),
    }
    resolved = resolve_model_dir("org/name", env=env)
    assert resolved == hf_hub_cache / "hub" / "models--org--name" / "snapshots" / "abc123"

    # XDG_CACHE_HOME fallback
    xdg = tmp_path / "xdg"
    repo = xdg / "huggingface" / "hub" / "models--org--name"
    (repo / "refs").mkdir(parents=True)
    (repo / "refs" / "main").write_text("def456\n")
    snap = repo / "snapshots" / "def456"
    snap.mkdir(parents=True)
    env_xdg = {"XDG_CACHE_HOME": str(xdg)}
    resolved2 = resolve_model_dir("org/name", env=env_xdg)
    assert resolved2 == snap

    # org-less id resolves under sentence-transformers
    st_repo = hf_hub_cache / "hub" / "models--sentence-transformers--minilm"
    (st_repo / "refs").mkdir(parents=True)
    (st_repo / "refs" / "main").write_text("xyz789\n")
    st_snap = st_repo / "snapshots" / "xyz789"
    st_snap.mkdir(parents=True)
    env_st = {"HF_HUB_CACHE": str(hf_hub_cache / "hub")}
    resolved3 = resolve_model_dir("minilm", env=env_st)
    assert resolved3 == st_snap

    # error lists searched paths
    with pytest.raises(FileNotFoundError) as exc:
        resolve_model_dir("other/name", env=env_st)
    msg = str(exc.value)
    assert "other/name" in msg
    assert str(hf_hub_cache / "hub") in msg


@pytest.mark.skipif(
    sys.version_info < (3, 9),
    reason="optional parity tests need a recent environment",
)
def test_tokenizer_parity_with_hf() -> None:
    try:
        from transformers import BertTokenizer, BertTokenizerFast
    except Exception:
        pytest.skip("transformers not installed")

    try:
        model_dir = resolve_model_dir("sentence-transformers/all-MiniLM-L6-v2")
    except FileNotFoundError:
        pytest.skip("MiniLM model not cached")

    vocab_path = model_dir / "vocab.txt"
    if not vocab_path.exists():
        vocab_path = model_dir / "0_Transformer" / "vocab.txt"
    if not vocab_path.exists():
        pytest.skip("vocab.txt not found in cached model")

    tok_hf_slow = BertTokenizer.from_pretrained(str(model_dir))
    tok_hf_fast = BertTokenizerFast.from_pretrained(str(model_dir))
    tok_np = WordPieceTokenizer.from_vocab_file(str(vocab_path), max_length=256)

    long_text = " ".join(f"w{i}" for i in range(300))

    corpus = [
        "",
        "   \t\n  ",
        "hello world",
        "The quick brown fox jumps over the lazy dog.",
        "Café, naïve, résumé: accents matter!",
        "Hello!!!   world???",
        "Tabs\tand\nnewlines\n\rare whitespace.",
        "我爱北京天安门",
        "mix 混合 text 文本 😊",
        "emoji 🚀🌟✨",
        "numbers 1,234.56; 12:34",
        "apostrophes aren't punctuation",
        "a" * 150,
        "word" * 80,
        "\x00control\x01chars\x02",
        "ΟΔΟΣ ΚΑΙ ΣΟΦΙΑ",
        "This text contains [CLS] and [SEP] and [MASK] and [PAD] literals.",
        "Reserved vocab entries like [unused1] and [unused993] are not special.",
        long_text,
    ]

    for text in corpus:
        ids_np = tok_np.encode(text)
        ids_slow = tok_hf_slow(text, truncation=True, max_length=256)["input_ids"]
        ids_fast = tok_hf_fast(text, truncation=True, max_length=256)["input_ids"]
        assert ids_np == ids_slow, f"slow mismatch for {text!r}: {ids_np} != {ids_slow}"
        assert ids_np == ids_fast, f"fast mismatch for {text!r}: {ids_np} != {ids_fast}"


def test_embedding_parity_with_sentence_transformers() -> None:
    try:
        import sentence_transformers
    except Exception:
        pytest.skip("sentence_transformers not installed")

    try:
        model_dir = resolve_model_dir("sentence-transformers/all-MiniLM-L6-v2")
    except FileNotFoundError:
        pytest.skip("MiniLM model not cached")

    if not (model_dir / "modules.json").exists():
        pytest.skip("MiniLM modules.json not found")

    model = sentence_transformers.SentenceTransformer(str(model_dir), device="cpu")
    embedder = NumpyMiniLMEmbedder(model_path=str(model_dir))
    asyncio.run(embedder.load())

    long_text = " ".join(f"w{i}" for i in range(300))

    corpus = [
        "",
        "hello world",
        "The quick brown fox jumps over the lazy dog.",
        "Café, naïve, résumé: accents matter!",
        "我爱北京天安门",
        "Tabs\tand\nnewlines\n\rare whitespace.",
        "apostrophes aren't punctuation",
        "This text contains [CLS] and [SEP] and [MASK] and [PAD] literals.",
        long_text,
    ]

    hf = model.encode(corpus, normalize_embeddings=False, convert_to_numpy=True)
    np_batch = asyncio.run(embedder.encode_batch(corpus))
    assert len(np_batch) == len(corpus)

    for i, (row_np, row_hf) in enumerate(zip(np_batch, hf)):
        row_np = np.asarray(row_np, dtype=np.float32)
        row_hf = np.asarray(row_hf, dtype=np.float32)
        assert row_np.shape == (384,)
        assert row_hf.shape == (384,)
        max_diff = float(np.max(np.abs(row_np - row_hf)))
        assert max_diff < 1e-5, f"batch row {i} max diff {max_diff}"
        cos = float(np.dot(row_np, row_hf) / (np.linalg.norm(row_np) * np.linalg.norm(row_hf)))
        assert cos >= 0.99999, f"batch row {i} cosine {cos}"

    for text in ["hello world", "Café naïve", "我爱北京天安门"]:
        v_np = np.asarray(asyncio.run(embedder.encode(text)), dtype=np.float32)
        v_hf = model.encode(text, normalize_embeddings=False, convert_to_numpy=True)
        assert np.max(np.abs(v_np - v_hf)) < 1e-5
        cos = float(np.dot(v_np, v_hf) / (np.linalg.norm(v_np) * np.linalg.norm(v_hf)))
        assert cos >= 0.99999

    empty_batch = asyncio.run(embedder.encode_batch([""]))
    assert len(empty_batch) == 1
    assert len(empty_batch[0]) == 384


def test_embedding_parity_numpy_erf_fallback(monkeypatch: Any) -> None:
    try:
        import sentence_transformers
    except Exception:
        pytest.skip("sentence_transformers not installed")

    try:
        model_dir = resolve_model_dir("sentence-transformers/all-MiniLM-L6-v2")
    except FileNotFoundError:
        pytest.skip("MiniLM model not cached")

    if not (model_dir / "modules.json").exists():
        pytest.skip("MiniLM modules.json not found")

    model = sentence_transformers.SentenceTransformer(str(model_dir), device="cpu")
    embedder = NumpyMiniLMEmbedder(model_path=str(model_dir))
    asyncio.run(embedder.load())

    monkeypatch.setattr(kaine.text_embedding_numpy, "_SCIPY_ERF", None)

    long_text = " ".join(f"w{i}" for i in range(300))

    corpus = [
        "",
        "hello world",
        "The quick brown fox jumps over the lazy dog.",
        "Café, naïve, résumé: accents matter!",
        "我爱北京天安门",
        "Tabs\tand\nnewlines\n\rare whitespace.",
        "apostrophes aren't punctuation",
        "This text contains [CLS] and [SEP] and [MASK] and [PAD] literals.",
        long_text,
    ]

    hf = model.encode(corpus, normalize_embeddings=False, convert_to_numpy=True)
    np_batch = asyncio.run(embedder.encode_batch(corpus))
    assert len(np_batch) == len(corpus)

    for i, (row_np, row_hf) in enumerate(zip(np_batch, hf)):
        row_np = np.asarray(row_np, dtype=np.float32)
        row_hf = np.asarray(row_hf, dtype=np.float32)
        assert row_np.shape == (384,)
        assert row_hf.shape == (384,)
        max_diff = float(np.max(np.abs(row_np - row_hf)))
        assert max_diff < 1e-5, f"batch row {i} max diff {max_diff}"
        cos = float(np.dot(row_np, row_hf) / (np.linalg.norm(row_np) * np.linalg.norm(row_hf)))
        assert cos >= 0.99999, f"batch row {i} cosine {cos}"

    for text in ["hello world", "Café naïve", "我爱北京天安门"]:
        v_np = np.asarray(asyncio.run(embedder.encode(text)), dtype=np.float32)
        v_hf = model.encode(text, normalize_embeddings=False, convert_to_numpy=True)
        assert np.max(np.abs(v_np - v_hf)) < 1e-5
        cos = float(np.dot(v_np, v_hf) / (np.linalg.norm(v_np) * np.linalg.norm(v_hf)))
        assert cos >= 0.99999

    empty_batch = asyncio.run(embedder.encode_batch([""]))
    assert len(empty_batch) == 1
    assert len(empty_batch[0]) == 384


def test_erf_numpy_matches_math_erf() -> None:
    xs = np.linspace(-6, 6, 2001)
    expected = np.array([math.erf(float(x)) for x in xs], dtype=np.float64)
    assert np.max(np.abs(_erf_numpy(xs) - expected)) <= 2e-7
