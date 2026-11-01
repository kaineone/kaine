# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Test helpers for companion streams (``kaine.bus.companion``).

A second fakeredis instance stands in for the never-persisted bus, so a test
can declare a companion stream, publish, and read the values back the way a
declared consumer does: the main entry, then its companion entry by the id its
envelope names.
"""

from __future__ import annotations

from typing import Any

from kaine.bus.companion import CompanionDeclaration
from kaine.bus.volatile import VolatileBus


def attach_test_volatile(bus: Any, *declarations: tuple[str, str]) -> VolatileBus:
    """Attach a fakeredis volatile instance to ``bus`` and declare each
    ``(stream, field_set)`` as a test consumer's companion stream."""
    import fakeredis.aioredis

    volatile = VolatileBus(client=fakeredis.aioredis.FakeRedis(decode_responses=True))
    bus.attach_volatile(volatile)
    bus.declare_companions(
        [CompanionDeclaration("test-consumer", stream, field_set) for stream, field_set in declarations]
    )
    return volatile


async def joined_entries(bus: Any, stream: str, *args: Any, **kwargs: Any) -> list[tuple[str, Any]]:
    """The entries of ``stream`` with each one's companion values put back."""
    out = []
    for entry_id, event in await bus.read(stream, *args, **kwargs):
        joined, _ok = await bus.join_companion(event)
        out.append((entry_id, joined))
    return out


#: Every stream whose words the shipped producers declare for the spoken-text
#: field set (``heard-text-volatile-bus``).
SPOKEN_STREAMS = (
    "audition.out",
    "embodiment.out",
    "language.external",
    "language.internal",
    "language.out",
    "episodic_memory.out",
)


def attach_spoken_test_volatile(bus: Any, *extra: tuple[str, str]) -> VolatileBus:
    """Attach a fakeredis volatile instance with every spoken-text stream declared."""
    return attach_test_volatile(bus, *[(s, "spoken_text") for s in SPOKEN_STREAMS], *extra)


async def joined_xrange(bus: Any, stream: str, **kwargs: Any) -> list[tuple[str, dict]]:
    """``XRANGE`` of ``stream`` with each entry's companion values put back into
    its JSON ``payload`` field, the way a declared consumer reads it."""
    import json

    from kaine.bus.client import _decode_entry

    out = []
    for entry_id, fields in await bus.client.xrange(stream, **kwargs):
        fields = dict(fields)
        decoded = _decode_entry(entry_id, fields)
        if decoded is not None and decoded[1].companion:
            joined, ok = await bus.join_companion(decoded[1])
            if ok:
                fields["payload"] = json.dumps(joined.payload, separators=(",", ":"))
        out.append((entry_id, fields))
    return out
