# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The headless operator text-stimulus injector for the minimal build."""
from __future__ import annotations

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.evaluation.benchmarks.workspace_mediation_ablation.inject import (
    inject_utterance,
    read_latest_external,
)


def _bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    return AsyncBus(BusConfig(password="x", audit_required=False), client=client)


@pytest.mark.asyncio
async def test_injected_utterance_lands_on_an_active_stream_as_audition():
    bus = _bus()
    # In a minimal build the cycle reads chronos.out (a registered module) but
    # NOT audition.out; inject onto the active stream.
    await inject_utterance(bus, "hello there", stream="chronos.out", seq=1)
    entries = await bus.read("chronos.out", last_id="0", count=10)
    assert len(entries) == 1
    _entry_id, event = entries[0]
    # Volition matches on source/type, not on the carrying stream — so the
    # utterance is recognized even though it rode chronos.out.
    assert event.source == "audition"
    assert event.type == "audition.transcription"
    assert event.payload["text"] == "hello there"
    await bus.close()


@pytest.mark.asyncio
async def test_read_latest_external_returns_none_when_silent():
    bus = _bus()
    assert await read_latest_external(bus) is None
    await bus.close()
