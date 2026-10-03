# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import json
import shutil
import subprocess

import httpx
import pytest

from kaine.bus.schema import Event
from kaine.lifecycle.manager import ForkManager
from kaine.nexus.app import create_app
from kaine.nexus.bridge import BusBridge
from kaine.nexus.config import NexusConfig
from kaine.nexus.conversation import ConversationState
from kaine.nexus.privacy import PrivacyFilter


class StubBus:
    async def read(self, stream, *, last_id, count, block_ms):
        return []

    async def current_workspace_id(self):
        return "0"


async def _make_client(
    *,
    config: NexusConfig | None = None,
    history: list[tuple[str, Event]] | None = None,
    metrics: dict | None = None,
    fork_manager: ForkManager | None = None,
    state: ConversationState | None = None,
    health_prober=None,
    rate_control_publisher=None,
    token: str | None = "test-token",
):
    # Conversation is deactivated by default in the base-thesis form; these router
    # tests exercise both surfaces, so enable conversation unless a test overrides.
    base = NexusConfig(
        conversation_enabled=True,
        # TestClient sends Host: test; allow it so CSRF validation passes.
        host_allowlist=("127.0.0.1", "localhost", "test"),
    )
    if config is None:
        config = base
    else:
        # Merge explicit overrides onto the test default.
        from dataclasses import replace

        config = replace(base, **config.__dict__)
    # TestClient sends Host: test; make sure it remains allowed after merging.
    if "test" not in config.host_allowlist:
        from dataclasses import replace

        config = replace(config, host_allowlist=(*config.host_allowlist, "test"))
    if token is not None:
        from dataclasses import replace

        config = replace(config, operator_token=token)
    bus = StubBus()
    privacy = PrivacyFilter(dev_content_override=config.dev_content_override)
    bridge = BusBridge(bus, privacy, streams=[], poll_interval_s=0.01)

    async def history_loader(n: int):
        return list(history or [])

    app = create_app(
        config=config,
        bridge=bridge,
        history_loader=history_loader,
        metrics_snapshot=lambda: dict(metrics or {}),
        fork_manager=fork_manager,
        conversation_state=state,
        health_prober=health_prober,
        rate_control_publisher=rate_control_publisher,
    )
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    return client, app


def test_merge_form_harness():
    if shutil.which("node") is None:
        pytest.skip("node not available")

    proc = subprocess.run(
        ["node", "tests/js/nexus_merge_form_harness.js"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    lines = proc.stdout.strip().splitlines()
    last = json.loads(lines[-1])
    assert last["ok"] is True


@pytest.mark.asyncio
async def test_diagnostics_page_renders_world_model_choice():
    client, app = await _make_client()
    async with app.router.lifespan_context(app):
        async with client:
            response = await client.get(
                "/diagnostics/",
                headers={"Authorization": "Bearer test-token"},
            )
            assert response.status_code == 200
            html = response.text
            assert '<label for="merge-world-model">world model from</label>' in html
            assert '<select id="merge-world-model">' in html
            assert 'value=""' in html
            assert 'value="a"' in html
            assert 'value="b"' in html
