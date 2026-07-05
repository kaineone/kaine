# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Boundary-neutral canonical list of Mnemos memory-collection kinds.

The four memory collection kinds were defined in
``kaine.modules.mnemos.memory`` and separately *mirrored* (hand-copied) in
``kaine.lifecycle.decommission`` — which must stay independent of
``kaine.modules``. Hosting the canonical tuple here lets both import the same
source of truth without the lifecycle subsystem reaching into a module.

stdlib-only; imports nothing else from ``kaine``.
"""
from __future__ import annotations

__all__ = ["MNEMOS_COLLECTION_KINDS"]

# Canonical Mnemos memory-collection kinds.
MNEMOS_COLLECTION_KINDS: tuple[str, str, str, str] = (
    "short_term",
    "episodic",
    "semantic",
    "procedural",
)
