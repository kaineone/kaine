# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Boundary-neutral text embedder + cosine similarity.

A dependency-light primitive shared by the evaluation sidecar (A/B
divergence, memory probes, individuation) AND by core modules that must
NOT import ``kaine.evaluation`` (the sidecar-decoupling boundary). It lives
here — alongside :mod:`kaine.privacy_filter` and
:mod:`kaine.persistence.jsonl_sink`, the other boundary-neutral primitives —
so a core module (e.g. Hypnos computing its consolidation-divergence
magnitude) can embed text without pulling in the evaluation subsystem.

``kaine.evaluation.embeddings`` re-exports everything here unchanged, so the
sidecar import sites are untouched.

This module is the SINGLE source of the sentence-transformer embedder. The
evaluation sidecar (``embed`` / ``cosine_similarity``), Hypnos
consolidation-divergence, and the memory/social modules (Mnemos, Empatheia,
which need ``encode`` / ``encode_batch`` / ``latent_dim`` / ``model_id`` /
``shutdown``) all share ONE wrapper here, so every subsystem embeds on the
same model and the same cosine scale. ``kaine.modules.mnemos.embeddings``
re-exports these names for back-compat without a second implementation.
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
from typing import Any, Iterable, Protocol, runtime_checkable

log = logging.getLogger(__name__)

DEFAULT_MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"

#: Output dimension of :data:`DEFAULT_MODEL_ID`. The Qdrant collection schemas
#: (Mnemos storage, Empatheia agent store) must be created with this size
#: BEFORE the embedder has loaded — its ``latent_dim`` is unknown until then —
#: so this is the single pinned value those schemas derive from. A loaded
#: embedder's ``latent_dim`` must equal this for the default model; the
#: storage layers assert vector dims against the collection size at write time.
DEFAULT_LATENT_DIM = 384


@runtime_checkable
class TextEmbedder(Protocol):
    async def load(self) -> None: ...
    async def embed(self, text: str) -> list[float]: ...


@runtime_checkable
class Embedder(Protocol):
    """Richer protocol used by the memory/social modules.

    A superset of :class:`TextEmbedder` adding batch encoding, the loaded
    model's latent dimension, the model id, and an explicit shutdown. The
    canonical :class:`SentenceTransformerTextEmbedder` satisfies both this
    and :class:`TextEmbedder`.
    """

    @property
    def latent_dim(self) -> int:
        """The loaded model's embedding dimension."""

    @property
    def model_id(self) -> str:
        """The embedding model id."""

    async def load(self) -> None:
        """Load the underlying model (idempotent)."""

    async def encode(self, text: str) -> list[float]:
        """Embed a single string to a vector."""

    async def encode_batch(self, texts: Iterable[str]) -> list[list[float]]:
        """Embed a batch of strings."""

    async def shutdown(self) -> None:
        """Release the model."""


class SentenceTransformerTextEmbedder:
    """The single sentence-transformer embedder for the whole system.

    Satisfies both the lightweight :class:`TextEmbedder` protocol
    (``load`` / ``embed``, used by the evaluation sidecar and Hypnos) and
    the richer :class:`Embedder` protocol (``encode`` / ``encode_batch`` /
    ``latent_dim`` / ``model_id`` / ``shutdown``, used by Mnemos and
    Empatheia). ``embed`` is an alias of ``encode`` so both names address
    the same vectors on the same cosine scale.

    Pins HF telemetry off so the runtime stays fully local after the
    first model download.
    """

    #: Embedder kind tag written into evaluation records for disclosure.
    kind: str = "sentence_transformers"

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL_ID,
        *,
        device_preference: str | None = "auto",
    ) -> None:
        self._model_id = model_id
        self._device_preference = device_preference
        self._device = "cpu"
        self._model: Any = None
        self._latent_dim: int | None = None

    @property
    def latent_dim(self) -> int:
        if self._latent_dim is None:
            raise RuntimeError("embedder not loaded; await .load() first")
        return self._latent_dim

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def device(self) -> str:
        return self._device

    async def load(self) -> None:
        if self._model is not None:
            return
        import asyncio

        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        from kaine.hardware import resolve_device

        # resolve_device falls back with a warning if the operator's
        # config asks for cuda:1 on a single-GPU host, instead of crashing.
        self._device = resolve_device(self._device_preference)

        def _load_sync():
            from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]

            return SentenceTransformer(self._model_id, device=self._device)

        self._model = await asyncio.to_thread(_load_sync)
        self._latent_dim = int(self._model.get_sentence_embedding_dimension())
        log.info(
            "embedder %s loaded on %s; latent_dim %d",
            self._model_id,
            self._device,
            self._latent_dim,
        )

    async def encode(self, text: str) -> list[float]:
        if self._model is None:
            await self.load()
        import asyncio

        def _encode_sync() -> list[float]:
            assert self._model is not None
            vec = self._model.encode(text, convert_to_numpy=True, show_progress_bar=False)
            return [float(x) for x in vec.tolist()]

        return await asyncio.to_thread(_encode_sync)

    async def encode_batch(self, texts: Iterable[str]) -> list[list[float]]:
        if self._model is None:
            await self.load()
        import asyncio

        items = list(texts)

        def _encode_sync() -> list[list[float]]:
            assert self._model is not None
            arr = self._model.encode(items, convert_to_numpy=True, show_progress_bar=False)
            return [[float(x) for x in row.tolist()] for row in arr]

        return await asyncio.to_thread(_encode_sync)

    async def embed(self, text: str) -> list[float]:
        """Alias of :meth:`encode` for the lightweight ``TextEmbedder`` callers."""
        return await self.encode(text)

    async def shutdown(self) -> None:
        self._model = None


class HashEmbedder:
    """Deterministic, dep-free embedder for tests and offline use.

    Hashes tokens into a fixed-dim vector. Not semantically meaningful,
    but cosine similarity stays in [0, 1] and is repeatable.
    """

    #: Embedder kind tag written into evaluation records for disclosure.
    kind: str = "hash"

    def __init__(self, dim: int = 64) -> None:
        self._dim = int(dim)

    async def load(self) -> None:
        return

    async def embed(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        for token in text.lower().split():
            # Stable across processes: Python's builtin hash() is salted per
            # process (PYTHONHASHSEED), which would make divergence/recall
            # metrics irreproducible across runs and operators. blake2b is
            # deterministic, so a seeded run reproduces its numbers.
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            h = int.from_bytes(digest, "big") % self._dim
            vec[h] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class FakeEmbedder:
    """Deterministic, fast, no-deps embedder for tests.

    Maps text → fixed-dim float vector via blake2b digest. Same text always
    yields the same vector; cosine similarity behaves usefully for
    substring overlap. Satisfies the richer :class:`Embedder` protocol
    (``encode`` / ``encode_batch`` / ``latent_dim`` / ``model_id`` /
    ``shutdown``).
    """

    def __init__(self, latent_dim: int = 32, model_id: str = "fake/embedder") -> None:
        if latent_dim <= 0 or latent_dim > 64:
            raise ValueError("latent_dim must be in (0, 64]")
        self._latent_dim = latent_dim
        self._model_id = model_id
        self.loaded = False
        self.shutdown_called = False

    @property
    def latent_dim(self) -> int:
        return self._latent_dim

    @property
    def model_id(self) -> str:
        return self._model_id

    async def load(self) -> None:
        self.loaded = True

    async def encode(self, text: str) -> list[float]:
        if not self.loaded:
            await self.load()
        digest = hashlib.blake2b(text.encode("utf-8"), digest_size=self._latent_dim).digest()
        # Map each byte to a float in [-1, 1]
        return [((b / 255.0) * 2.0 - 1.0) for b in digest]

    async def encode_batch(self, texts: Iterable[str]) -> list[list[float]]:
        return [await self.encode(t) for t in texts]

    async def shutdown(self) -> None:
        self.shutdown_called = True


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (na * nb)))
