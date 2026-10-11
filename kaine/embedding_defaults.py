# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Default constants for text embedders."""

DEFAULT_MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"

#: Output dimension of :data:`DEFAULT_MODEL_ID`. Storage is sized from the
#: embedder's ``latent_dim``; this value is the fallback for an embedder that
#: cannot report its dimension before it loads (the sentence-transformers
#: backend), and the default for the test embedders.
DEFAULT_LATENT_DIM = 384

#: Embedding-space stamp for legacy memory stores created before KAINE
#: started stamping every collection with its embedding space. This is the
#: only model KAINE shipped before stamping; a store with no stamp and
#: existing points is assumed to be in this space.
LEGACY_EMBEDDING_SPACE = {
    "model_id": DEFAULT_MODEL_ID,
    "dim": DEFAULT_LATENT_DIM,
    "pooling": "mean",
    "normalized": True,
}


def canonical_model_id(model_id: str) -> str:
    """Return ``model_id`` with its HuggingFace org, as sentence-transformers
    resolves it: an id without ``/`` names a ``sentence-transformers`` model."""
    return model_id if "/" in model_id else f"sentence-transformers/{model_id}"
