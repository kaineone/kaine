# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_nexus_routers import _make_client


class _FakeHealthProber:
    cache_ttl_s = 0.0

    async def snapshot(self):
        return SimpleNamespace(
            dependencies=[
                SimpleNamespace(
                    name="test-service",
                    role="test-role",
                    status="up",
                    detail="ok",
                    checked_at="2026-01-01T00:00:00+00:00",
                )
            ],
            modules=[],
        )


@pytest.mark.asyncio
async def test_health_sidebar_details_always_visible_and_no_duplicate_heading():
    client, app = await _make_client(health_prober=_FakeHealthProber())
    async with client:
        async with app.router.lifespan_context(app):
            response = await client.get("/diagnostics/", headers={"Authorization": "Bearer test-token"})
    response.raise_for_status()
    html = response.text

    # The duplicate board heading is gone; the section title from the parent remains.
    assert "service &amp; dependency health" not in html
    # Dependency details are rendered in the markup (always-visible now via CSS).
    assert 'class="dep-detail"' in html

    style_path = (
        Path(__file__).resolve().parents[1]
        / "kaine"
        / "nexus"
        / "static"
        / "style.css"
    )
    css = style_path.read_text(encoding="utf-8")
    assert "grid-template-rows: auto 0fr 0fr" not in css
    assert ".health-row:hover .dep-detail" not in css
