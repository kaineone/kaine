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


async def joined_entries(bus: Any, stream: str, last_id: str = "0") -> list[tuple[str, Any]]:
    """The entries of ``stream`` with each one's companion values put back."""
    out = []
    for entry_id, event in await bus.read(stream, last_id=last_id):
        joined, _ok = await bus.join_companion(event)
        out.append((entry_id, joined))
    return out
