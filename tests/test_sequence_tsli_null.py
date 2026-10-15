# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from datetime import datetime, timezone

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.faithful.templates import TEMPLATES
from kaine.modules.affect import Affect


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


@pytest.mark.asyncio
async def test_affect_ignores_null_tsli(bus: AsyncBus):
    affect = Affect(bus, clock=lambda: 0.0, publish_interval_s=999.0)
    await affect.initialize()
    try:
        null_event = Event(
            source="sequence",
            type="sequence.report",
            payload={"time_since_last_interaction_s": None},
            salience=0.1,
            timestamp=datetime.now(timezone.utc),
        )
        await affect._handle_peer_event(affect._sequence_stream, null_event)
        assert affect._interaction_seen is False

        finite_event = Event(
            source="sequence",
            type="sequence.report",
            payload={"time_since_last_interaction_s": 8.0},
            salience=0.1,
            timestamp=datetime.now(timezone.utc),
        )
        await affect._handle_peer_event(affect._sequence_stream, finite_event)
        assert affect._interaction_seen is True
    finally:
        await affect.shutdown()


def test_renderer_skips_null_tsli():
    render = TEMPLATES[("sequence", "sequence.report")]
    text = render(
        {
            "anomaly_score": 0.1,
            "habituation_score": 0.2,
            "time_since_last_interaction_s": None,
        }
    )
    assert "seconds since interaction" not in text


def test_renderer_shows_finite_tsli():
    render = TEMPLATES[("sequence", "sequence.report")]
    text = render(
        {
            "anomaly_score": 0.1,
            "habituation_score": 0.2,
            "time_since_last_interaction_s": 12.5,
        }
    )
    assert "12.5 seconds since interaction" in text
