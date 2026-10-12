# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Boundary-neutral canonical list of the episodic memory module's memory-collection kinds.

The four memory collection kinds were defined in
``kaine.modules.episodic_memory.memory`` and separately *mirrored* (hand-copied) in
``kaine.lifecycle.decommission`` — which must stay independent of
``kaine.modules``. Hosting the canonical tuple here lets both import the same
source of truth without the lifecycle subsystem reaching into a module.

stdlib-only; imports nothing else from ``kaine``.
"""
from __future__ import annotations

import uuid

__all__ = [
    "EPISODIC_MEMORY_COLLECTION_KINDS",
    "EPISODIC_MEMORY_STAMP_COLLECTION",
    "EPISODIC_MEMORY_STORE_HEALTH_PATH",
    "stamp_key",
    "stamp_point_id",
    "strength_key",
]

# Canonical episodic memory-collection kinds.
EPISODIC_MEMORY_COLLECTION_KINDS: tuple[str, str, str, str] = (
    "short_term",
    "episodic",
    "semantic",
    "procedural",
)

#: Shared Qdrant collection used for embedding-space stamps.
EPISODIC_MEMORY_STAMP_COLLECTION: str = "kaine_meta"

#: Shared path to the episodic memory module's store health state file written by the episodic memory module and read by the dashboard.
EPISODIC_MEMORY_STORE_HEALTH_PATH: str = "state/mnemos/store_health.json"

#: Fixed namespace for deriving deterministic Qdrant point ids for
#: ``kaine_meta`` embedding-space stamps.
_STAMP_NAMESPACE: uuid.UUID = uuid.UUID(
    "a7c1f3e2-4b2c-4f6d-9e8a-1c2d3e4f5a6b"
)


def stamp_key(prefix: str) -> str:
    """Canonical embedding-space stamp key for a collection prefix."""
    return f"{prefix}embedding_space"


def stamp_point_id(key: str) -> str:
    """Deterministic Qdrant point id for an embedding-space stamp key."""
    return str(uuid.uuid5(_STAMP_NAMESPACE, key))


def strength_key(prefix: str) -> str:
    """Key of the trace-strength record (episodic memory module meta) for a collection prefix."""
    return f"{prefix}strength"
