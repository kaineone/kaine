# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Media metadata that no rendering and no memory of the entity may hold.

The vision and audition modules stamp ``item``, the basename of the playlist
media file being played (an operator-chosen file name, often a film title), on
their reports so an operator can read off the bus which item is playing. The
entity perceives the film, not its file name (the eyes-and-ears rule), so the
field never reaches the organ's prompt, the intent log, the voice-alignment
training pairs or an episodic trace. ``item_order``, the manifest position, is
a number and is not listed.

One list serves every surface: the renderers (``FaithfulRenderer.render_event``
and ``fallback_template`` in ``kaine.faithful``) and the episodic memory store
(``kaine.faithful.episodic_own_content``). Any payload key a module fills from
a playlist position's ``title`` belongs here; a test checks the producers.
"""

from __future__ import annotations

from typing import Any

MEDIA_METADATA_FIELDS: frozenset[str] = frozenset({"item"})


def without_media_metadata(value: Any, extra: frozenset[str] = frozenset()) -> Any:
    """A copy of ``value`` with every mapping key in ``MEDIA_METADATA_FIELDS``
    (and ``extra``) removed at any depth, including inside lists and tuples.

    The copy is plain: tuples come back as lists and mapping subclasses as
    ``dict``. Bus payloads are decoded JSON, so producers emit neither."""
    keys = MEDIA_METADATA_FIELDS | extra
    return _without(value, keys)


def _without(value: Any, keys: frozenset[str]) -> Any:
    if isinstance(value, dict):
        return {k: _without(v, keys) for k, v in value.items() if k not in keys}
    if isinstance(value, (list, tuple)):
        return [_without(v, keys) for v in value]
    return value
