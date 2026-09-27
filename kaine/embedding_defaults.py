# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Default constants for text embedders."""

DEFAULT_MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"

#: Output dimension of :data:`DEFAULT_MODEL_ID`. Storage is sized from the
#: embedder's ``latent_dim``; this value is the fallback for an embedder that
#: cannot report its dimension before it loads (the sentence-transformers
#: backend), and the default for the test embedders.
DEFAULT_LATENT_DIM = 384
