# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import json
import shutil
import subprocess

import httpx
import pytest

from kaine.bus.schema import Event
from kaine.dashboard.app import create_app
from kaine.dashboard.bridge import BusBridge
from kaine.dashboard.config import DashboardConfig
from kaine.dashboard.conversation import ConversationState
from kaine.dashboard.privacy import PrivacyFilter
from kaine.lifecycle.manager import ForkManager


class StubBus:
    async def read(self, stream, *, last_id, count, block_ms):
        return []

    async def current_workspace_id(self):
        return "0"


async def _make_client(
    *,
    config: DashboardConfig | None = None,
    history: list[tuple[str, Event]] | None = None,
    metrics: dict | None = None,
    fork_manager: ForkManager | None = None,
    state: ConversationState | None = None,
    health_prober=None,
    rate_control_publisher=None,
    token: str | None = "test-token",
):
    # Conversation is deactivated by default in the first configuration; these router
    # tests exercise both surfaces, so enable conversation unless a test overrides.
    base = DashboardConfig(
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
        ["node", "tests/js/dashboard_merge_form_harness.js"],
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


@pytest.mark.asyncio
async def test_diagnostics_page_renders_module_weights_choice():
    client, app = await _make_client()
    async with app.router.lifespan_context(app):
        async with client:
            response = await client.get(
                "/diagnostics/",
                headers={"Authorization": "Bearer test-token"},
            )
            assert response.status_code == 200
            html = response.text
            assert '<label for="merge-module-weights">module weights from</label>' in html
            start = html.index('<select id="merge-module-weights">')
            select = html[start : html.index("</select>", start)]
            for value in ('value=""', 'value="a"', 'value="b"'):
                assert value in select


def _vision_snapshots(mgr: ForkManager) -> tuple[str, str]:
    from unittest.mock import MagicMock

    from kaine.bus.client import AsyncBus
    from kaine.modules.context import CONTEXT_DIM
    from kaine.modules.vision.forward import LatentForwardModel
    from kaine.modules.vision.module import Vision

    class _Encoder:
        model_id = "test/encoder"
        latent_dim = 4
        clip_len = 1

    class _Registry:
        def __init__(self, module):
            self._module = module

        def all_modules(self):
            return iter([self._module])

    ids = []
    for seed in (1, 2):
        vision = Vision(MagicMock(spec=AsyncBus), encoder=_Encoder(), forward_prediction=True)
        vision._forward_model = LatentForwardModel(
            latent_dim=4, units=3, seed=seed, context_dim=CONTEXT_DIM
        )
        ids.append(mgr.snapshot(_Registry(vision)).id)
    return ids[0], ids[1]


@pytest.mark.asyncio
async def test_merge_api_refuses_differing_module_weights_naming_the_module(tmp_path):
    mgr = ForkManager(tmp_path / "forks")
    a, b = _vision_snapshots(mgr)
    client, app = await _make_client(fork_manager=mgr)
    async with app.router.lifespan_context(app):
        async with client:
            response = await client.post(
                "/diagnostics/merges",
                json={"snapshot_a_id": a, "snapshot_b_id": b},
                headers={"Authorization": "Bearer test-token", "Origin": "http://test"},
            )
            assert response.status_code == 409, response.text
            assert "vision" in response.json()["detail"]
            assert len(mgr.list_snapshots()) == 2

            response = await client.post(
                "/diagnostics/merges",
                json={"snapshot_a_id": a, "snapshot_b_id": b, "module_weights_from": "b"},
                headers={"Authorization": "Bearer test-token", "Origin": "http://test"},
            )
            assert response.status_code == 200, response.text
            merged = mgr.load(response.json()["id"])
            assert merged.metadata["module_weights_from"]["vision"] == {
                "from": "b",
                "reason": "chosen",
            }
