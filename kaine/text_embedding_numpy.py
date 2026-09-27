# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""NumPy-only BERT-style text embedder.

This module implements a tiny, dependency-light sentence-transformer-like
embedder that uses only the Python standard library and NumPy.  It reads
safetensors weights directly, runs a full BERT/MiniLM forward pass in
float32, and applies mean pooling + L2 normalization.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import struct
import unicodedata
from pathlib import Path
from typing import Any

import numpy as np

from kaine.text_embedding import DEFAULT_LATENT_DIM, DEFAULT_MODEL_ID

log = logging.getLogger(__name__)

__all__ = [
    "read_safetensors",
    "WordPieceTokenizer",
    "resolve_model_dir",
    "NumpyMiniLMEmbedder",
    "bert_forward",
    "mean_pool_normalize",
]

try:
    from scipy.special import erf as _SCIPY_ERF
except ImportError:
    _SCIPY_ERF = None

SAFETENSORS_DTYPES: dict[str, tuple[np.dtype[Any], int]] = {
    "F32": (np.dtype("<f4"), 4),
    "F16": (np.dtype("<f2"), 2),
    "I64": (np.dtype("<i8"), 8),
    "I32": (np.dtype("<i4"), 4),
}


def read_safetensors(path: str | Path) -> dict[str, np.ndarray]:
    """Read a minimal safetensors file.

    Supports F32, F16 (upcast to float32), and the integer buffers I64/I32
    some checkpoints carry.  Rejects truncated files, offset overruns,
    and unsupported dtypes.
    """
    raw = Path(path).read_bytes()
    if len(raw) < 8:
        raise ValueError(f"safetensors file truncated: {path}")

    (header_len,) = struct.unpack("<Q", raw[:8])
    header_end = 8 + header_len
    if header_end > len(raw):
        raise ValueError(
            f"safetensors header length {header_len} exceeds file size {len(raw)}"
        )

    header = json.loads(raw[8:header_end].decode("utf-8"))
    if not isinstance(header, dict):
        raise ValueError("safetensors header is not a JSON object")

    data_start = header_end
    data_len = len(raw) - data_start
    tensors: dict[str, np.ndarray] = {}

    for name, info in header.items():
        if not isinstance(info, dict):
            continue  # e.g. __metadata__
        dtype_key = info.get("dtype")
        shape = info.get("shape")
        offsets = info.get("data_offsets")
        if dtype_key is None or shape is None or offsets is None:
            continue

        if dtype_key not in SAFETENSORS_DTYPES:
            raise ValueError(
                f"unsupported safetensors dtype {dtype_key!r} for tensor {name!r}"
            )

        np_dtype, itemsize = SAFETENSORS_DTYPES[dtype_key]
        start, end = offsets
        if start < 0 or end < start or end > data_len:
            raise ValueError(
                f"tensor {name!r} data_offsets {offsets} overrun the data area"
            )

        count = int(np.prod(shape, dtype=np.int64))
        expected = count * itemsize
        if end - start != expected:
            raise ValueError(
                f"tensor {name!r} size mismatch: offsets span {end - start}, "
                f"expected {expected}"
            )

        offset = data_start + start
        arr = np.frombuffer(raw, dtype=np_dtype, count=count, offset=offset)
        arr = arr.reshape(shape)
        if dtype_key in {"F16", "F32"}:
            arr = arr.astype(np.float32, copy=False)
        tensors[name] = arr

    return tensors


class WordPieceTokenizer:
    """BERT-style basic + WordPiece tokenizer (no dependency on transformers)."""

    def __init__(
        self,
        vocab: dict[str, int],
        *,
        do_lower_case: bool = True,
        strip_accents: bool | None = None,
        tokenize_chinese_chars: bool = True,
        max_length: int = 256,
        unk_token: str = "[UNK]",
        cls_token: str = "[CLS]",
        sep_token: str = "[SEP]",
        mask_token: str = "[MASK]",
        never_split: set[str] | None = None,
    ) -> None:
        self.vocab = vocab
        self.do_lower_case = do_lower_case
        if strip_accents is None:
            strip_accents = do_lower_case
        self.strip_accents = strip_accents
        self.tokenize_chinese_chars = tokenize_chinese_chars
        self.max_length = int(max_length)
        self.unk_token = unk_token
        self.cls_token = cls_token
        self.sep_token = sep_token
        self.mask_token = mask_token
        self.unk_id = vocab[unk_token]
        self.cls_id = vocab[cls_token]
        self.sep_id = vocab[sep_token]
        self.mask_id = vocab[mask_token]

        never_split = set(never_split) if never_split else set()
        for tok in (unk_token, cls_token, sep_token, mask_token):
            never_split.add(tok)
        # Only the declared special tokens are matched whole, as HuggingFace
        # does; other bracketed vocab entries such as ``[unused1]`` are split.
        special_tokens = [t for t in vocab if t in never_split]
        # Longest first so a shorter token doesn't steal a prefix of a longer one.
        special_tokens.sort(key=len, reverse=True)
        self.special_tokens = set(special_tokens)
        if special_tokens:
            self._special_re = re.compile(
                "(" + "|".join(re.escape(t) for t in special_tokens) + ")"
            )
        else:
            self._special_re = None

    @classmethod
    def from_vocab_file(
        cls,
        path: str | Path,
        *,
        do_lower_case: bool = True,
        strip_accents: bool | None = None,
        tokenize_chinese_chars: bool = True,
        max_length: int = 256,
        never_split: set[str] | None = None,
    ) -> "WordPieceTokenizer":
        vocab_path = Path(path)
        vocab: dict[str, int] = {}
        with open(vocab_path, "r", encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                token = line.rstrip("\n")
                if token:
                    vocab[token] = i

        special_tokens: set[str] = set(never_split) if never_split else set()
        tc_path = vocab_path.with_name("tokenizer_config.json")
        if tc_path.exists():
            tc = json.loads(tc_path.read_text())
            if "do_lower_case" in tc:
                do_lower_case = tc["do_lower_case"]
            if "strip_accents" in tc:
                strip_accents = tc["strip_accents"]
            if "tokenize_chinese_chars" in tc:
                tokenize_chinese_chars = tc["tokenize_chinese_chars"]
            ns = tc.get("never_split")
            if ns:
                special_tokens.update(
                    t.get("content") if isinstance(t, dict) else t for t in ns
                )
            stm = tc.get("special_tokens_map") or {}
            for key in ("unk_token", "cls_token", "sep_token", "mask_token", "pad_token"):
                tok = stm.get(key) or tc.get(key)
                if isinstance(tok, dict):
                    tok = tok.get("content")
                if isinstance(tok, str):
                    special_tokens.add(tok)

        return cls(
            vocab,
            do_lower_case=do_lower_case,
            strip_accents=strip_accents,
            tokenize_chinese_chars=tokenize_chinese_chars,
            max_length=max_length,
            never_split=special_tokens,
        )

    def tokenize(self, text: str) -> list[str]:
        """Return wordpiece tokens, preserving literal special tokens."""
        pieces: list[str] = []
        if self._special_re is None:
            segments = [text]
        else:
            segments = self._special_re.split(text)
        for segment in segments:
            if segment in self.special_tokens:
                pieces.append(segment)
            else:
                for token in self._basic_tokenize(segment):
                    pieces.extend(self._wordpiece_tokenize(token))
        return pieces

    def encode(self, text: str) -> list[int]:
        """Return token ids including [CLS] and [SEP], truncated to max_length."""
        pieces = self.tokenize(text)
        if len(pieces) > self.max_length - 2:
            pieces = pieces[: self.max_length - 2]
        return [self.cls_id] + [self.vocab.get(t, self.unk_id) for t in pieces] + [self.sep_id]

    @staticmethod
    def _is_whitespace(char: str) -> bool:
        return char in " \t\n\r" or unicodedata.category(char) == "Zs"

    @staticmethod
    def _is_control(char: str) -> bool:
        cat = unicodedata.category(char)
        return cat.startswith("C") and char not in "\t\n\r"

    @staticmethod
    def _is_punctuation(char: str) -> bool:
        cp = ord(char)
        if (33 <= cp <= 47) or (58 <= cp <= 64) or (91 <= cp <= 96) or (123 <= cp <= 126):
            return True
        return unicodedata.category(char).startswith("P")

    @staticmethod
    def _is_chinese_char(cp: int) -> bool:
        return (
            (0x4E00 <= cp <= 0x9FFF)
            or (0x3400 <= cp <= 0x4DBF)
            or (0x20000 <= cp <= 0x2A6DF)
            or (0x2A700 <= cp <= 0x2B73F)
            or (0x2B740 <= cp <= 0x2B81F)
            or (0x2B820 <= cp <= 0x2CEAF)
            or (0xF900 <= cp <= 0xFAFF)
            or (0x2F800 <= cp <= 0x2FA1F)
        )

    def _clean_text(self, text: str) -> str:
        out: list[str] = []
        for char in text:
            cp = ord(char)
            if cp == 0 or cp == 0xFFFD or self._is_control(char):
                continue
            if self._is_whitespace(char):
                out.append(" ")
            else:
                out.append(char)
        return "".join(out)

    def _tokenize_chinese_chars(self, text: str) -> str:
        out: list[str] = []
        for char in text:
            cp = ord(char)
            if self._is_chinese_char(cp):
                out.extend([" ", char, " "])
            else:
                out.append(char)
        return "".join(out)

    @staticmethod
    def _run_strip_accents(text: str) -> str:
        text = unicodedata.normalize("NFD", text)
        return "".join(c for c in text if unicodedata.category(c) != "Mn")

    def _run_split_on_punc(self, text: str) -> list[str]:
        if not text:
            return []
        chars = list(text)
        start_new_word = True
        output: list[list[str]] = []
        for char in chars:
            if self._is_punctuation(char):
                output.append([char])
                start_new_word = True
            else:
                if start_new_word:
                    output.append([])
                output[-1].append(char)
                start_new_word = False
        return ["".join(x) for x in output]

    def _basic_tokenize(self, text: str) -> list[str]:
        text = self._clean_text(text)
        if self.tokenize_chinese_chars:
            text = self._tokenize_chinese_chars(text)
        orig_tokens = text.split()
        split_tokens: list[str] = []
        for token in orig_tokens:
            if self.do_lower_case:
                token = "".join(ch.lower() for ch in token)
            if self.strip_accents:
                token = self._run_strip_accents(token)
            split_tokens.extend(self._run_split_on_punc(token))
        return split_tokens

    def _wordpiece_tokenize(self, text: str) -> list[str]:
        if len(text) > 100:
            return [self.unk_token]

        output: list[str] = []
        start = 0
        while start < len(text):
            end = len(text)
            cur_substr: str | None = None
            while start < end:
                substr = text[start:end]
                if start > 0:
                    substr = "##" + substr
                if substr in self.vocab:
                    cur_substr = substr
                    break
                end -= 1
            if cur_substr is None:
                return [self.unk_token]
            output.append(cur_substr)
            start += len(cur_substr.replace("##", ""))
        return output


def resolve_model_dir(
    model_id: str,
    model_path: str | Path | None = None,
    *,
    env: dict[str, str] | None = None,
) -> Path:
    """Resolve a sentence-transformers model directory.

    If ``model_path`` is given it is returned directly.  Otherwise the HF
    hub cache is inspected in this order:

    * ``HF_HUB_CACHE``
    * ``HUGGINGFACE_HUB_CACHE``
    * ``HF_HOME/hub``
    * ``XDG_CACHE_HOME/huggingface/hub``
    * ``~/.cache/huggingface/hub``

    Within a hub directory ``models--<org>--<name>/refs/main`` points to
    ``snapshots/<rev>``.  If the ref is missing, the single snapshot
    directory is used as a fallback.
    """
    if model_path is not None:
        return Path(model_path)

    if env is None:
        env = os.environ

    if "/" not in model_id:
        model_id = f"sentence-transformers/{model_id}"

    org, name = model_id.split("/", 1)

    candidates: list[Path] = []
    if env.get("HF_HUB_CACHE"):
        candidates.append(Path(env["HF_HUB_CACHE"]))
    if env.get("HUGGINGFACE_HUB_CACHE"):
        candidates.append(Path(env["HUGGINGFACE_HUB_CACHE"]))
    if env.get("HF_HOME"):
        candidates.append(Path(env["HF_HOME"]) / "hub")
    if env.get("XDG_CACHE_HOME"):
        candidates.append(Path(env["XDG_CACHE_HOME"]) / "huggingface" / "hub")
    candidates.append(Path.home() / ".cache" / "huggingface" / "hub")

    searched: list[str] = []

    for hub_dir in candidates:
        if not hub_dir.is_dir():
            searched.append(str(hub_dir))
            continue

        repo_dir = hub_dir / f"models--{org}--{name}"
        searched.append(str(repo_dir))
        if not repo_dir.is_dir():
            continue

        refs_main = repo_dir / "refs" / "main"
        snapshot_dir = repo_dir / "snapshots"

        if refs_main.exists():
            rev = refs_main.read_text().strip()
            resolved = snapshot_dir / rev
            if resolved.is_dir():
                return resolved
            searched.append(str(refs_main))
            searched.append(str(resolved))
        elif snapshot_dir.is_dir():
            snaps = [d for d in snapshot_dir.iterdir() if d.is_dir()]
            if len(snaps) == 1:
                return snaps[0]
            searched.append(str(snapshot_dir))

    raise FileNotFoundError(
        f"model directory not found for {model_id}; searched: {', '.join(searched)}"
    )


def _erf_numpy(x: np.ndarray) -> np.ndarray:
    """Vectorised Abramowitz–Stegun 7.1.26 erf approximation in float64.

    Maximum absolute error is about 1.5e-7.  Used as a fallback on hosts
    without SciPy.
    """
    x64 = x.astype(np.float64)
    sign = np.sign(x64)
    x_abs = np.abs(x64)
    p = 0.3275911
    t = 1.0 / (1.0 + p * x_abs)
    a1, a2, a3, a4, a5 = (
        0.254829592,
        -0.284496736,
        1.421413741,
        -1.453152027,
        1.061405429,
    )
    poly = t * (a1 + t * (a2 + t * (a3 + t * (a4 + t * a5))))
    y = 1.0 - poly * np.exp(-x_abs * x_abs)
    return (sign * y).astype(np.float32)


def _erf(x: np.ndarray) -> np.ndarray:
    """Exact erf; prefers scipy.special.erf when available.

    Falls back to the NumPy Abramowitz–Stegun 7.1.26 approximation
    (maximum absolute error 1.5e-7) on hosts without SciPy.
    """
    if _SCIPY_ERF is not None:
        return _SCIPY_ERF(x).astype(np.float32)
    return _erf_numpy(x)


def gelu(x: np.ndarray) -> np.ndarray:
    """Exact GELU activation (erf form)."""
    return (x * 0.5 * (1.0 + _erf(x / np.sqrt(2.0)))).astype(np.float32)


def layer_norm(
    x: np.ndarray,
    gamma: np.ndarray,
    beta: np.ndarray,
    eps: float,
) -> np.ndarray:
    """PyTorch-compatible LayerNorm (population variance)."""
    mean = x.mean(axis=-1, keepdims=True)
    var = x.var(axis=-1, keepdims=True, ddof=0)
    return ((x - mean) / np.sqrt(var + eps)) * gamma + beta


def _linear(x: np.ndarray, weight: np.ndarray, bias: np.ndarray) -> np.ndarray:
    """PyTorch-style linear: x @ W.T + b."""
    return x @ weight.T + bias


def _canonical_weight(weights: dict[str, np.ndarray], name: str) -> np.ndarray:
    """Fetch a weight by its BERT name, with optional ``bert.`` prefix."""
    if name in weights:
        return weights[name]
    prefixed = "bert." + name
    if prefixed in weights:
        return weights[prefixed]
    raise KeyError(name)


def bert_forward(
    weights: dict[str, np.ndarray],
    config: dict[str, Any],
    input_ids_batch: np.ndarray,
    attention_mask: np.ndarray,
) -> np.ndarray:
    """Run a BERT/MiniLM encoder and return the last hidden state."""
    batch, seq = input_ids_batch.shape
    hidden = int(config["hidden_size"])
    num_layers = int(config["num_hidden_layers"])
    num_heads = int(config["num_attention_heads"])
    head_dim = hidden // num_heads
    eps = float(config.get("layer_norm_eps", 1e-12))

    # Embeddings
    word_w = _canonical_weight(weights, "embeddings.word_embeddings.weight")
    pos_w = _canonical_weight(weights, "embeddings.position_embeddings.weight")
    type_w = _canonical_weight(weights, "embeddings.token_type_embeddings.weight")
    ln_g = _canonical_weight(weights, "embeddings.LayerNorm.weight")
    ln_b = _canonical_weight(weights, "embeddings.LayerNorm.bias")

    x = word_w[input_ids_batch]
    positions = np.arange(seq, dtype=np.int64)
    x = x + pos_w[positions]
    x = x + type_w[0]
    x = layer_norm(x, ln_g, ln_b, eps)

    mask = attention_mask[:, None, None, :]

    for layer in range(num_layers):
        # Self-attention
        q = _linear(
            x,
            _canonical_weight(weights, f"encoder.layer.{layer}.attention.self.query.weight"),
            _canonical_weight(weights, f"encoder.layer.{layer}.attention.self.query.bias"),
        )
        k = _linear(
            x,
            _canonical_weight(weights, f"encoder.layer.{layer}.attention.self.key.weight"),
            _canonical_weight(weights, f"encoder.layer.{layer}.attention.self.key.bias"),
        )
        v = _linear(
            x,
            _canonical_weight(weights, f"encoder.layer.{layer}.attention.self.value.weight"),
            _canonical_weight(weights, f"encoder.layer.{layer}.attention.self.value.bias"),
        )

        q = q.reshape(batch, seq, num_heads, head_dim).transpose(0, 2, 1, 3)
        k = k.reshape(batch, seq, num_heads, head_dim).transpose(0, 2, 1, 3)
        v = v.reshape(batch, seq, num_heads, head_dim).transpose(0, 2, 1, 3)

        scores = (q @ k.transpose(0, 1, 3, 2)) / math.sqrt(head_dim)
        scores = np.where(mask, scores, np.finfo(np.float32).min)

        # stable softmax
        scores = scores - scores.max(axis=-1, keepdims=True)
        exp = np.exp(scores)
        attn = exp / exp.sum(axis=-1, keepdims=True)

        context = attn @ v
        context = context.transpose(0, 2, 1, 3).reshape(batch, seq, hidden)

        out = _linear(
            context,
            _canonical_weight(weights, f"encoder.layer.{layer}.attention.output.dense.weight"),
            _canonical_weight(weights, f"encoder.layer.{layer}.attention.output.dense.bias"),
        )
        x = layer_norm(
            x + out,
            _canonical_weight(weights, f"encoder.layer.{layer}.attention.output.LayerNorm.weight"),
            _canonical_weight(weights, f"encoder.layer.{layer}.attention.output.LayerNorm.bias"),
            eps,
        )

        # FFN
        h = _linear(
            x,
            _canonical_weight(weights, f"encoder.layer.{layer}.intermediate.dense.weight"),
            _canonical_weight(weights, f"encoder.layer.{layer}.intermediate.dense.bias"),
        )
        h = gelu(h)
        out2 = _linear(
            h,
            _canonical_weight(weights, f"encoder.layer.{layer}.output.dense.weight"),
            _canonical_weight(weights, f"encoder.layer.{layer}.output.dense.bias"),
        )
        x = layer_norm(
            x + out2,
            _canonical_weight(weights, f"encoder.layer.{layer}.output.LayerNorm.weight"),
            _canonical_weight(weights, f"encoder.layer.{layer}.output.LayerNorm.bias"),
            eps,
        )

    return x


def mean_pool_normalize(hidden: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Mean pooling with a real-token mask, then L2 normalization."""
    mask_f = mask[..., None].astype(np.float32)
    pooled = (hidden.astype(np.float32) * mask_f).sum(axis=1)
    sum_mask = mask_f.sum(axis=1)
    sum_mask = np.maximum(sum_mask, 1e-9)
    pooled = pooled / sum_mask

    sq = (pooled * pooled).sum(axis=-1, keepdims=True)
    norm = np.sqrt(sq)
    norm = np.maximum(norm, 1e-12)
    return (pooled / norm).astype(np.float32)


def _locate_file(model_dir: Path, *candidates: str) -> Path | None:
    for rel in candidates:
        path = model_dir / rel
        if path.exists():
            return path
    return None


def _load_json_config(model_dir: Path) -> dict[str, Any] | None:
    path = _locate_file(model_dir, "config.json", "0_Transformer/config.json")
    if path is None:
        return None
    return json.loads(path.read_text())


def _load_tokenizer_settings(model_dir: Path) -> dict[str, Any]:
    path = _locate_file(model_dir, "tokenizer_config.json", "0_Transformer/tokenizer_config.json")
    if path is None:
        return {}
    tc = json.loads(path.read_text())
    settings: dict[str, Any] = {}
    if "do_lower_case" in tc:
        settings["do_lower_case"] = tc["do_lower_case"]
    if "strip_accents" in tc:
        settings["strip_accents"] = tc["strip_accents"]
    if "tokenize_chinese_chars" in tc:
        settings["tokenize_chinese_chars"] = tc["tokenize_chinese_chars"]

    special_tokens: set[str] = set()
    ns = tc.get("never_split")
    if ns:
        special_tokens.update(
            t.get("content") if isinstance(t, dict) else t for t in ns
        )
    stm = tc.get("special_tokens_map") or {}
    for key in ("unk_token", "cls_token", "sep_token", "mask_token", "pad_token"):
        tok = stm.get(key) or tc.get(key)
        if isinstance(tok, dict):
            tok = tok.get("content")
        if isinstance(tok, str):
            special_tokens.add(tok)
    if special_tokens:
        settings["never_split"] = special_tokens
    return settings


def _validate_weights(weights: dict[str, np.ndarray], config: dict[str, Any]) -> None:
    """Check that every tensor the BERT forward pass reads is present and shaped."""
    hidden = int(config["hidden_size"])
    vocab = int(config["vocab_size"])
    positions = int(config["max_position_embeddings"])
    type_vocab = int(config.get("type_vocab_size", 2))
    layers = int(config["num_hidden_layers"])
    intermediate = int(config["intermediate_size"])

    def check(name: str, expected: tuple[int, ...]) -> None:
        key = name
        if key not in weights:
            alt = "bert." + name
            if alt in weights:
                key = alt
            else:
                raise ValueError(f"weight {name!r} is missing")
        shape = tuple(weights[key].shape)
        if shape != expected:
            raise ValueError(
                f"weight {key!r} has shape {shape}, expected {expected}"
            )

    check("embeddings.word_embeddings.weight", (vocab, hidden))
    check("embeddings.position_embeddings.weight", (positions, hidden))
    check("embeddings.token_type_embeddings.weight", (type_vocab, hidden))
    check("embeddings.LayerNorm.weight", (hidden,))
    check("embeddings.LayerNorm.bias", (hidden,))

    for layer in range(layers):
        pfx = f"encoder.layer.{layer}"
        check(f"{pfx}.attention.self.query.weight", (hidden, hidden))
        check(f"{pfx}.attention.self.query.bias", (hidden,))
        check(f"{pfx}.attention.self.key.weight", (hidden, hidden))
        check(f"{pfx}.attention.self.key.bias", (hidden,))
        check(f"{pfx}.attention.self.value.weight", (hidden, hidden))
        check(f"{pfx}.attention.self.value.bias", (hidden,))
        check(f"{pfx}.attention.output.dense.weight", (hidden, hidden))
        check(f"{pfx}.attention.output.dense.bias", (hidden,))
        check(f"{pfx}.attention.output.LayerNorm.weight", (hidden,))
        check(f"{pfx}.attention.output.LayerNorm.bias", (hidden,))
        check(f"{pfx}.intermediate.dense.weight", (intermediate, hidden))
        check(f"{pfx}.intermediate.dense.bias", (intermediate,))
        check(f"{pfx}.output.dense.weight", (hidden, intermediate))
        check(f"{pfx}.output.dense.bias", (hidden,))
        check(f"{pfx}.output.LayerNorm.weight", (hidden,))
        check(f"{pfx}.output.LayerNorm.bias", (hidden,))


class NumpyMiniLMEmbedder:
    """NumPy-only sentence-transformer-style embedder.

    Satisfies the existing :class:`kaine.text_embedding.Embedder` protocol.
    """

    kind: str = "numpy_minilm"

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL_ID,
        *,
        model_path: str | Path | None = None,
    ) -> None:
        self.model_id = model_id
        self.model_path = model_path
        self._model_dir: Path | None = None
        self._config: dict[str, Any] | None = None
        self._weights: dict[str, np.ndarray] | None = None
        self._tokenizer: WordPieceTokenizer | None = None
        self._loaded = False
        self._latent_dim = DEFAULT_LATENT_DIM

        try:
            self._model_dir = resolve_model_dir(model_id, model_path=model_path)
            cfg = _load_json_config(self._model_dir)
            if cfg is not None:
                self._latent_dim = int(cfg["hidden_size"])
        except (FileNotFoundError, KeyError, json.JSONDecodeError):
            pass

    @property
    def latent_dim(self) -> int:
        return self._latent_dim

    async def load(self) -> None:
        """Load model weights, config and tokenizer (idempotent)."""
        if self._loaded:
            return

        def _load_sync() -> None:
            model_dir = self._model_dir
            if model_dir is None:
                model_dir = resolve_model_dir(self.model_id, model_path=self.model_path)
                self._model_dir = model_dir

            modules_path = model_dir / "modules.json"
            if not modules_path.exists():
                raise FileNotFoundError(f"modules.json not found in {model_dir}")
            modules = json.loads(modules_path.read_text())
            if not isinstance(modules, list) or len(modules) != 3:
                raise ValueError(
                    "modules.json must contain exactly Transformer → Pooling → Normalize"
                )
            for expected, mod in zip(
                ("Transformer", "Pooling", "Normalize"), modules
            ):
                mod_type = mod.get("type", "")
                if expected not in mod_type:
                    raise ValueError(
                        f"modules.json module type {mod_type!r} is not {expected!r}"
                    )

            pool_path = model_dir / "1_Pooling" / "config.json"
            if not pool_path.exists():
                raise FileNotFoundError(f"pooling config not found: {pool_path}")
            pool_cfg = json.loads(pool_path.read_text())
            if not pool_cfg.get("pooling_mode_mean_tokens", False):
                raise ValueError("1_Pooling/config.json pooling_mode_mean_tokens must be true")
            for key in (
                "pooling_mode_cls_token",
                "pooling_mode_max_tokens",
                "pooling_mode_mean_sqrt_len_tokens",
                "pooling_mode_lasttoken",
                "pooling_mode_whole_word_tokens",
                "pooling_mode_weightedmean_tokens",
            ):
                if pool_cfg.get(key, False):
                    raise ValueError(f"1_Pooling/config.json {key} must be false")

            sbc_path = model_dir / "sentence_bert_config.json"
            max_length = 256
            if sbc_path.exists():
                sbc = json.loads(sbc_path.read_text())
                max_length = int(sbc.get("max_seq_length", max_length))

            cfg = _load_json_config(model_dir)
            if cfg is None:
                raise FileNotFoundError(f"config.json not found in {model_dir}")

            model_type = cfg.get("model_type")
            if model_type != "bert":
                raise ValueError(f"model_type {model_type!r} is not 'bert'")
            hidden_act = cfg.get("hidden_act", "gelu")
            if hidden_act != "gelu":
                raise ValueError(f"hidden_act {hidden_act!r} is not 'gelu'")
            position_embedding_type = cfg.get("position_embedding_type", "absolute")
            if position_embedding_type != "absolute":
                raise ValueError(
                    f"position_embedding_type {position_embedding_type!r} is not supported"
                )

            vocab_path = _locate_file(model_dir, "vocab.txt", "0_Transformer/vocab.txt")
            if vocab_path is None:
                raise FileNotFoundError(f"vocab.txt not found in {model_dir}")

            weights_path = _locate_file(
                model_dir,
                "model.safetensors",
                "0_Transformer/model.safetensors",
            )
            if weights_path is None:
                raise FileNotFoundError(f"model.safetensors not found in {model_dir}")

            weights = read_safetensors(weights_path)
            _validate_weights(weights, cfg)

            hidden_size = int(cfg["hidden_size"])
            if hidden_size != self._latent_dim:
                raise ValueError(
                    f"latent_dim mismatch: config {hidden_size} vs expected {self._latent_dim}"
                )

            tokenizer_settings = _load_tokenizer_settings(model_dir)
            self._config = cfg
            self._tokenizer = WordPieceTokenizer.from_vocab_file(
                vocab_path, max_length=max_length, **tokenizer_settings
            )
            self._weights = weights
            self._loaded = True
            log.info(
                "numpy MiniLM embedder loaded from %s; latent_dim %d",
                model_dir,
                hidden_size,
            )

        await asyncio.to_thread(_load_sync)

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            raise RuntimeError("embedder not loaded; await .load() first")

    async def encode(self, text: str) -> list[float]:
        self._ensure_loaded()
        return (await self.encode_batch([text]))[0]

    async def encode_batch(self, texts: Any) -> list[list[float]]:
        self._ensure_loaded()

        def _encode_sync() -> list[list[float]]:
            assert self._tokenizer is not None
            assert self._config is not None
            assert self._weights is not None

            if len(texts) == 0:
                return []

            ids_batch = [self._tokenizer.encode(str(t)) for t in texts]
            max_len = max((len(ids) for ids in ids_batch), default=0)
            input_ids = np.zeros((len(ids_batch), max_len), dtype=np.int64)
            mask = np.zeros((len(ids_batch), max_len), dtype=np.int64)
            for i, ids in enumerate(ids_batch):
                input_ids[i, : len(ids)] = ids
                mask[i, : len(ids)] = 1

            hidden = bert_forward(self._weights, self._config, input_ids, mask)
            pooled = mean_pool_normalize(hidden, mask)
            return [[float(x) for x in row] for row in pooled]

        return await asyncio.to_thread(_encode_sync)

    async def embed(self, text: str) -> list[float]:
        """Alias of :meth:`encode` for the lightweight protocol."""
        return await self.encode(text)

    async def shutdown(self) -> None:
        """Release the model."""
        self._loaded = False
        self._weights = None
        self._tokenizer = None
