# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Browser-side status chip tests for the KAINE dashboard console."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from kaine.dashboard.app import create_app
from kaine.dashboard.bridge import BusBridge
from kaine.dashboard.config import DashboardConfig
from kaine.dashboard.conversation import ConversationState
from kaine.dashboard.privacy import PrivacyFilter

ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "kaine" / "dashboard" / "static"
HARNESS = ROOT / "tests" / "js" / "dashboard_status_chip_harness.js"
SOURCE = STATIC_DIR / "dashboard.js"


class StubBus:
    async def read(self, stream, *, last_id, count, block_ms):
        return []

    async def current_workspace_id(self):
        return "0"


async def _make_app_client(*, state: ConversationState, startup=None):
    config = DashboardConfig(
        conversation_enabled=True,
        host_allowlist=("127.0.0.1", "localhost", "test"),
        operator_token="test-token",
    )
    bus = StubBus()
    privacy = PrivacyFilter()
    bridge = BusBridge(bus, privacy, streams=[], poll_interval_s=0.01)

    async def history_loader(n: int):
        return []

    app = create_app(
        config=config,
        bridge=bridge,
        history_loader=history_loader,
        metrics_snapshot=lambda: {"cycle_status": "not running"},
        conversation_state=state,
        startup=startup,
    )
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    return client, app


def test_dashboard_status_chip_js_syntax():
    if not shutil.which("node"):
        pytest.skip("node not available")
    result = subprocess.run(
        ["node", "--check", str(SOURCE)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(not shutil.which("node"), reason="node not available")
def test_dashboard_status_chip_js_harness():
    result = subprocess.run(
        ["node", str(HARNESS)],
        capture_output=True,
        text=True,
    )
    print(result.stdout)
    print(result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    output = json.loads(result.stdout.splitlines()[-1])
    assert output["ok"] is True


@pytest.mark.asyncio
async def test_console_page_shows_escaped_entity_name():
    state = ConversationState()
    state.entity_name = "<b>Lyra</b>"
    state.sleeping = False
    client, _app = await _make_app_client(state=state)
    async with client:
        response = await client.get("/", headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 200
    text = response.text
    assert '<p class="rail__entity" id="entity-name">&lt;b&gt;Lyra&lt;/b&gt;</p>' in text
    assert "<b>Lyra</b>" not in text


@pytest.mark.asyncio
async def test_console_page_data_sleeping_true():
    state = ConversationState()
    state.entity_name = "KAINE"
    state.sleeping = True
    client, _app = await _make_app_client(state=state)
    async with client:
        response = await client.get("/", headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 200
    assert 'data-sleeping="true"' in response.text
    assert 'id="sleep-badge"' in response.text


@pytest.mark.asyncio
async def test_console_page_data_sleeping_false():
    state = ConversationState()
    state.entity_name = "KAINE"
    state.sleeping = False
    client, _app = await _make_app_client(state=state)
    async with client:
        response = await client.get("/", headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 200
    assert 'data-sleeping="false"' in response.text
    assert 'id="sleep-badge"' in response.text
