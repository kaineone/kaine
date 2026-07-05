# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Workspace-snapshot -> fixed-width observation vector.

Phantasia's world model does NOT see pixels or audio. Its "observation" is a
small fixed-width vector of DERIVED NUMERIC SUMMARIES of the access-conscious
content of one :class:`WorkspaceSnapshot`:

  * a per-source salience-weighted coalition bucket (one float per known
    module source — how loudly that source spoke into the workspace this tick),
  * an affect summary (intensity / valence / dominance) read from any
    ``thymos.state`` event present in the coalition,
  * the inhibition flag (1.0 when the broadcast was inhibited, else 0.0).

This contains NO raw audio bytes, NO image bytes, NO transcript text — only
floats derived from event source/type/salience and numeric affect. That is the
zero-persistence-preserving representation the trajectory buffer stores.

The layout is VERSIONED (``VERSION``) so a workspace-schema change that shifts
the vector can be detected rather than silently drifting (design.md "Risks").

Pure stdlib — no numpy / no jax — so the suite encodes observations without the
``[worldmodel]`` extra. The world model converts the returned list to arrays.
"""
from __future__ import annotations

from typing import Any

from kaine.cycle.types import WorkspaceSnapshot

VERSION: str = "phantasia-encoder-v1"

# Stable, ordered list of module sources that may appear in the coalition.
# Order is LOAD-BEARING: it fixes the observation-vector layout for VERSION.
# Appending a new source (and bumping VERSION) is the supported evolution path.
SOURCE_ORDER: tuple[str, ...] = (
    "soma",
    "chronos",
    "topos",
    "audition",
    "vox",
    "mnemos",
    "nous",
    "thymos",
    "eidolon",
    "empatheia",
    "lingua",
    "praxis",
    "perception",
    "mundus",
    "phantasia",
)

# Affect summary slots (intensity, valence, dominance) + inhibition flag.
_AFFECT_DIM = 3
_FLAG_DIM = 1

OBS_DIM: int = len(SOURCE_ORDER) + _AFFECT_DIM + _FLAG_DIM


def observation_dim() -> int:
    """Fixed width of the observation vector for the current ``VERSION``."""
    return OBS_DIM


def _clip01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def encode_snapshot(snapshot: WorkspaceSnapshot) -> list[float]:
    """Encode one workspace snapshot to a fixed-width observation vector.

    Returns a plain ``list[float]`` of length :data:`OBS_DIM`. The vector is a
    derived numeric summary only — it never carries raw sense data.
    """
    source_index = {src: i for i, src in enumerate(SOURCE_ORDER)}
    buckets = [0.0] * len(SOURCE_ORDER)

    affect_intensity = 0.0
    affect_valence = 0.0
    affect_dominance = 0.0

    for _entry_id, event in snapshot.selected_events or []:
        idx = source_index.get(event.source)
        if idx is not None:
            # Accumulate salience per source (a source can speak more than once).
            buckets[idx] = _clip01(buckets[idx] + float(event.salience))
        # Read affect from a thymos.state event if one is in the coalition.
        if event.type == "thymos.state":
            state = event.payload.get("state") or {}
            try:
                affect_intensity = _clip01(abs(float(state.get("arousal", 0.0))))
                affect_valence = float(state.get("valence", 0.0))
                affect_dominance = float(state.get("dominance", 0.0))
            except (TypeError, ValueError):
                pass

    vector = list(buckets)
    vector.append(affect_intensity)
    vector.append(affect_valence)
    vector.append(affect_dominance)
    vector.append(1.0 if snapshot.inhibited else 0.0)
    return vector
