# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Bus subsystem: schema validation, publish/read roundtrip, audit refusal."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import EventValidationError, validate_event

from tests.systems._harness import SubsystemHarness


@pytest.mark.asyncio
async def test_publish_read_roundtrip():
    async with SubsystemHarness() as h:
        entry_id = await h.inject(
            "soma.out", source="soma", type="soma.tick", payload={"v": 1}
        )
        assert entry_id
        entries = await h.bus.read("soma.out", last_id="0")
        assert len(entries) == 1
        _, event = entries[0]
        assert event.source == "soma"
        assert event.payload == {"v": 1}


@pytest.mark.asyncio
async def test_publish_to_reserved_workspace_rejected():
    from kaine.bus.schema import ReservedStreamError, ensure_writable

    with pytest.raises(ReservedStreamError):
        ensure_writable("workspace.broadcast", "soma")


def test_validate_event_rejects_out_of_range_salience():
    with pytest.raises(EventValidationError):
        validate_event(
            source="soma",
            type="x",
            payload={},
            salience=1.5,
            timestamp=datetime.now(timezone.utc),
        )


def test_validate_event_rejects_negative_salience():
    with pytest.raises(EventValidationError):
        validate_event(
            source="soma",
            type="x",
            payload={},
            salience=-0.1,
            timestamp=datetime.now(timezone.utc),
        )


@pytest.mark.asyncio
async def test_workspace_broadcast_helper():
    async with SubsystemHarness() as h:
        await h.broadcast_workspace({"tick_index": 7, "selected": []})
        # Workspace stream uses the snapshot format, not the standard
        # event format; read raw entries via the underlying client.
        raw = await h.bus._client.xrange("workspace.broadcast")
        assert len(raw) == 1
