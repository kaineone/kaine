# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""No shipped module follows a stream with a non-blocking read from "$".

Every module is built with the same lightweight doubles the revive tests use,
initialised on a fakeredis-backed bus whose read methods are spied on, and left
to run its background loops briefly. Any read whose cursor is "$" without a
block time is recorded: such a read can never return an entry, and the bus now
refuses it, so a consumer doing it would silently follow nothing.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from kaine.setup.wizard import MODULE_ORDER
from tests import test_revive_each_module as revive
from tests.test_revive_each_module import _plaintext_encryptor, _run_context  # noqa: F401

_BUILDERS = {
    name: getattr(revive, f"_build_{name}")
    for name in MODULE_ORDER
    if hasattr(revive, f"_build_{name}")
}


def test_every_configurable_module_has_a_builder():
    # Echo is the only configurable module without a revive builder; it reads
    # no stream with a cursor (grep: no read_entries in kaine/modules/echo).
    missing = sorted(set(MODULE_ORDER) - set(_BUILDERS) - {"echo"})
    assert not missing, f"add a _build_<name> for {missing} to test_revive_each_module"


@pytest.fixture
async def spied_bus():
    from kaine.bus.client import AsyncBus
    from kaine.bus.config import BusConfig

    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(
        decode_responses=True, max_connections=BusConfig().max_connections
    )
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    calls: list[tuple[str, str, Any]] = []

    real_read_entries = bus.read_entries
    real_block = bus.read_entries_block

    async def read_entries(stream, last_id="0", count=100, block_ms=0):
        calls.append((stream, last_id, block_ms))
        return await real_read_entries(stream, last_id, count, block_ms)

    async def read_entries_block(streams, *, count=100, block_ms=0):
        for stream, cursor in streams.items():
            calls.append((stream, cursor, block_ms))
        return await real_block(streams, count=count, block_ms=block_ms)

    bus.read_entries = read_entries
    bus.read_entries_block = read_entries_block
    yield bus, calls
    await bus.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", sorted(_BUILDERS))
async def test_module_never_reads_from_dollar_without_blocking(
    name: str, spied_bus, tmp_path: Path
) -> None:
    bus, calls = spied_bus
    module = await _BUILDERS[name](bus, tmp_path, name)
    try:
        # Let every background loop poll a few times.
        await asyncio.sleep(0.4)
    finally:
        await module.shutdown()
    bad = [(stream, cursor) for stream, cursor, block in calls if cursor == "$" and not block]
    assert not bad, f"{name} reads {bad} from '$' without blocking"
