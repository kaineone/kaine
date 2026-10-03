# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The diagnostics page renders while no cycle is running and controls are on.

The metrics snapshot for a stopped cycle carries only ``cycle_status`` and a
hint, so the rate-control form must not read the rate keys as present.
"""

from __future__ import annotations

import pytest

from tests.test_nexus_routers import _make_client


class _Publisher:
    async def __call__(self, *args, **kwargs):
        return None


@pytest.mark.asyncio
async def test_diagnostics_renders_with_controls_and_no_cycle():
    client, app = await _make_client(
        metrics={"cycle_status": "not running", "hint": "start the cycle"},
        rate_control_publisher=_Publisher(),
    )
    async with client:
        async with app.router.lifespan_context(app):
            r = await client.get(
                "/diagnostics/", headers={"Authorization": "Bearer test-token"}
            )
    assert r.status_code == 200, r.text[:500]
    assert 'id="rate-form"' in r.text
    assert 'id="exp-rate-effective"' not in r.text


@pytest.mark.asyncio
async def test_diagnostics_shows_effective_rate_when_present():
    client, app = await _make_client(
        metrics={
            "cycle_status": "running",
            "experiential_rate_hz": 3.33,
            "experiential_rate_effective_hz": 5.0,
            "access_drive": 0.4,
        },
        rate_control_publisher=_Publisher(),
    )
    async with client:
        async with app.router.lifespan_context(app):
            r = await client.get(
                "/diagnostics/", headers={"Authorization": "Bearer test-token"}
            )
    assert r.status_code == 200
    assert "conscious access now 5.00 Hz" in r.text
