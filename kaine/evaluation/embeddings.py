# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Small embedder for cosine similarity in A/B divergence and memory probes.

The implementation lives in the boundary-neutral :mod:`kaine.text_embedding`
so a core module (which must NOT import ``kaine.evaluation``) can reuse the
same embedder + cosine — e.g. Hypnos computing its consolidation-divergence
magnitude on the same scale as the A/B meter. This module re-exports it
unchanged so every evaluation import site stays put.
"""
from __future__ import annotations

from kaine.text_embedding import (
    DEFAULT_MODEL_ID,
    HashEmbedder,
    SentenceTransformerTextEmbedder,
    TextEmbedder,
    cosine_similarity,
)

__all__ = [
    "DEFAULT_MODEL_ID",
    "HashEmbedder",
    "SentenceTransformerTextEmbedder",
    "TextEmbedder",
    "cosine_similarity",
]
