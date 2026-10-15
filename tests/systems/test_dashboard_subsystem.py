# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The dashboard subsystem: routes return expected shapes with the privacy boundary."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from kaine.bus.schema import Event
from kaine.dashboard.app import create_app
from kaine.dashboard.bridge import BusBridge
from kaine.dashboard.config import DashboardConfig
from kaine.dashboard.privacy import PrivacyFilter


class StubBus:
    async def read(self, stream, *, last_id="0", count=100, block_ms=0):
        return []

    async def current_workspace_id(self):
        return "0"


@pytest.mark.asyncio
async def test_diagnostics_route_returns_200():
    config = DashboardConfig()
    bridge = BusBridge(StubBus(), PrivacyFilter(), streams=[])

    async def history_loader(n):
        return []

    app = create_app(
        config=config,
        bridge=bridge,
        history_loader=history_loader,
        metrics_snapshot=lambda: {"cycle_status": "not running"},
        fork_manager=None,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8088") as c:
        async with app.router.lifespan_context(app):
            r = await c.get("/diagnostics/")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_diagnostics_strips_content_at_bridge():
    pf = PrivacyFilter()
    ev = Event(
        source="language",
        type="external_speech",
        payload={"text": "private", "metric": 1},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )
    out = pf.filter(ev, surface="diagnostics")
    assert "text" not in out.payload
    assert out.payload == {"metric": 1}


@pytest.mark.asyncio
async def test_no_surface_passes_content_through():
    # The privacy boundary holds for every surface: there is no unfiltered
    # surface, so even a "conversation" surface name content-strips.
    pf = PrivacyFilter()
    ev = Event(
        source="language",
        type="external_speech",
        payload={"text": "hello", "metric": 1},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )
    out = pf.filter(ev, surface="conversation")
    assert "text" not in out.payload
    assert out.payload == {"metric": 1}
