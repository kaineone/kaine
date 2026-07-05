# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Live-Redis integration tests for the event bus.

These tests are skipped unless KAINE_REDIS_PASSWORD is set in the environment.
Run them only after the operator has hardened the system Redis per SETUP.md
§1.2: bind loopback, requirepass set, appendonly yes, appendfsync everysec.
"""
from datetime import datetime, timezone

import pytest

from kaine.bus import Event, get_bus
from kaine.bus.client import AsyncBus
from kaine.bus.config import load_bus_config
from kaine.bus.schema import module_stream


pytestmark = pytest.mark.integration


def _event(source: str = "soma", salience: float = 0.5, **payload) -> Event:
    return Event(
        source=source,
        type="integration.test",
        payload=payload or {"k": "v"},
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_audit_passes_against_hardened_redis():
    cfg = load_bus_config()
    bus = AsyncBus(cfg)
    try:
        await bus.audit()
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_publish_and_read_roundtrip_live_redis():
    cfg = load_bus_config()
    bus = AsyncBus(cfg)
    try:
        await bus.audit()
        stream = module_stream("soma")
        await bus.client.delete(stream)

        ev = _event(salience=0.30000000000000004, nested={"a": [1, 2, 3]})
        await bus.publish(ev)
        entries = await bus.read(stream, last_id="0")
        assert len(entries) == 1
        _, got = entries[0]
        assert got.salience == 0.30000000000000004
        assert got.payload == {"nested": {"a": [1, 2, 3]}}
        await bus.client.delete(stream)
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_get_bus_audits_on_first_call():
    bus = await get_bus()
    assert bus is not None
    same = await get_bus()
    assert bus is same
    await bus.close()
