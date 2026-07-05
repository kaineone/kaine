# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Counter-based, seed-keyed PRNG shared by the deterministic perception feeds.

Both the video source (``kaine/modules/topos/feed.py``) and the audio source
(``kaine/modules/audition/feed.py``) synthesize a stimulus that is a *pure
function of* ``(seed, frame_index)`` so a research run reproduces bit-identically
and is seek-safe. They draw their randomness from the same counter-based keyed
PRNG below — a single shared implementation, so the two surfaces stay in lockstep
on shared cadence slots and there is no copy-pasted PRNG logic to drift apart.

WHY A COUNTER-BASED PRNG: a stateless/seekable draw means frame ``i`` yields the
same value regardless of the path taken to it (restart-safe), unlike
``random.Random`` which is sequential. Anticipating a future draw from observed
stimulus would require inverting blake2b keyed on the seed — computationally
infeasible — which is exactly the "reproducible for the experimenter, not
predictable to the entity" property the design calls for.

BOUNDARIES: this leaf module lives under ``kaine.modules`` and imports nothing
but the standard library, so both perception modules may import it freely without
crossing any ``lint-imports`` contract (no cycle-runtime, no nexus, no evaluation
import here).
"""
from __future__ import annotations

import hashlib
import struct

__all__ = ["keyed_u64", "unit_float"]


def keyed_u64(seed: int, frame_index: int, salt: int) -> int:
    """Counter-based, seed-keyed 64-bit PRNG draw.

    A stateless/seekable draw: frame ``i`` yields the same value regardless of
    the path taken to it (restart-safe). ``salt`` namespaces independent draw
    streams for the same ``(seed, frame_index)`` so the base signal, the surprise
    onset, and the surprise content never collide.
    """
    key = struct.pack("<qqq", int(seed), int(frame_index), int(salt))
    digest = hashlib.blake2b(key, digest_size=8).digest()
    return int.from_bytes(digest, "little", signed=False)


def unit_float(value_u64: int) -> float:
    """Map a 64-bit draw into ``[0, 1)``."""
    return (value_u64 >> 11) / float(1 << 53)
