# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Shared definitions for external (other-initiated) input events.

External-input types are events whose entire text payload is heard input
produced by someone else, not by the being.
"""

from __future__ import annotations

from typing import Any, Iterator

# Other-initiated workspace coalition member types.
# These events carry heard input: every text value in their payload is speech
# said to or near the entity.
EXTERNAL_INPUT_TYPES = frozenset({"audition.transcription", "mundus.chat"})


def iter_text_leaves(value: Any) -> Iterator[str]:
    """Yield every non-empty stripped `str` found recursively in dicts, lists
    and tuples.
    """
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            yield stripped
    elif isinstance(value, dict):
        for child in value.values():
            yield from iter_text_leaves(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from iter_text_leaves(child)
