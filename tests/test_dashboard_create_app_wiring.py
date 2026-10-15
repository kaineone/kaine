# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from kaine.dashboard.app import create_app
from kaine.dashboard.auth import require_operator_token
from kaine.dashboard.bridge import BusBridge
from kaine.dashboard.config import DashboardConfig
from kaine.dashboard.privacy import PrivacyFilter


def test_dashboard_main_create_app_keywords_are_accepted():
    """Every keyword passed to create_app() from kaine/dashboard/__main__.py must be
    declared by create_app(), otherwise the dashboard crashes at startup."""
    main_path = Path(__file__).resolve().parents[1] / "kaine" / "dashboard" / "__main__.py"
    source = main_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    sig = inspect.signature(create_app)
    params = sig.parameters

    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "create_app"
    ]
    assert calls, "expected at least one create_app() call in __main__.py"

    for call in calls:
        for keyword in call.keywords:
            arg = keyword.arg
            assert arg in params, (
                f"__main__.py passes keyword {arg!r} to create_app(), "
                f"but create_app() does not accept that parameter"
            )


class _StubBus:
    async def read(self, stream, *, last_id, count, block_ms):
        return []

    async def current_workspace_id(self):
        return "0"


def test_create_app_forwards_fork_manager_reason():
    """create_app() must pass fork_manager_reason through to
    /diagnostics/forks.json when no fork manager is present."""
    config = DashboardConfig(
        diagnostics_enabled=True,
        host_allowlist=("127.0.0.1", "localhost", "test"),
        operator_token="test-token",
    )
    bus = _StubBus()
    privacy = PrivacyFilter(dev_content_override=config.dev_content_override)
    bridge = BusBridge(bus, privacy, streams=[], poll_interval_s=0.01)
    bridge.start = AsyncMock()
    bridge.stop = AsyncMock()

    async def history_loader(n: int):
        return []

    app = create_app(
        config=config,
        bridge=bridge,
        history_loader=history_loader,
        metrics_snapshot=lambda: {},
        fork_manager=None,
        fork_manager_reason="the state-encryption posture could not be installed",
    )
    app.dependency_overrides[require_operator_token] = lambda: None

    expected_reason = (
        "fork operations are disabled: the state-encryption posture could not be "
        "installed (see the Dashboard log)"
    )

    with TestClient(app, base_url="http://test") as client:
        response = client.get("/diagnostics/forks.json")

    assert response.status_code == 200
    data = response.json()
    assert data["available"] is False
    assert data["reason"] == expected_reason
