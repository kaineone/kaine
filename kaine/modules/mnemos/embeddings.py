# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Text embedders for Mnemos — re-export of the single, boundary-neutral wrapper.

The sentence-transformer embedder used to be duplicated here. It now lives in
:mod:`kaine.text_embedding`, the boundary-neutral home shared by the
evaluation sidecar, Hypnos, Mnemos and Empatheia, so every subsystem embeds
on the SAME model (`sentence-transformers/all-MiniLM-L6-v2`, 384-dim,
Apache-2.0, CPU-capable) and the SAME cosine scale. This module re-exports
those names so existing Mnemos import sites keep working; there is no second
implementation.

``SentenceTransformerEmbedder`` is kept as an alias of the canonical
``SentenceTransformerTextEmbedder`` for back-compat with callers and tests.
"""
from __future__ import annotations

from kaine.text_embedding import (
    DEFAULT_MODEL_ID,
    Embedder,
    FakeEmbedder,
    SentenceTransformerTextEmbedder,
)

#: Back-compat alias. The single model id lives in ``kaine.text_embedding``.
DEFAULT_EMBEDDER_MODEL_ID: str = DEFAULT_MODEL_ID

#: Back-compat alias for the canonical embedder class.
SentenceTransformerEmbedder = SentenceTransformerTextEmbedder

__all__ = [
    "DEFAULT_EMBEDDER_MODEL_ID",
    "Embedder",
    "FakeEmbedder",
    "SentenceTransformerEmbedder",
    "SentenceTransformerTextEmbedder",
]
