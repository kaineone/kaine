# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the welfare board's sleep/rest panel and affect welfare record."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from kaine.dashboard.app import create_app
from kaine.dashboard.bridge import BusBridge
from kaine.dashboard.config import DashboardConfig
from kaine.dashboard.conversation import ConversationState
from kaine.dashboard.diagnostics import _templates
from kaine.dashboard.privacy import PrivacyFilter

ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "kaine" / "dashboard" / "static"
TEMPLATE_DIR = ROOT / "kaine" / "dashboard" / "templates"
SOURCE = STATIC_DIR / "dashboard_sleep.js"
SLEEP_PANEL = TEMPLATE_DIR / "_sleep_panel.html"
HARNESS = ROOT / "tests" / "js" / "dashboard_sleep_harness.js"


def test_dashboard_sleep_js_syntax():
    if not shutil.which("node"):
        pytest.skip("node not available")
    result = subprocess.run(
        ["node", "--check", str(SOURCE)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(not shutil.which("node"), reason="node not available")
def test_dashboard_sleep_js_harness():
    result = subprocess.run(["node", str(HARNESS)], capture_output=True, text=True)
    print(result.stdout)
    print(result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    output = json.loads(result.stdout.splitlines()[-1])
    assert output["ok"] is True


def test_sleep_panel_no_inline_handlers():
    text = SLEEP_PANEL.read_text(encoding="utf-8")
    assert not re.search(r"\son\w+\s*=", text, re.IGNORECASE)


def test_partials_are_included():
    sections = (TEMPLATE_DIR / "_diagnostics_sections.html").read_text(encoding="utf-8")
    assert '{% include "_affect_welfare.html" %}' in sections
    assert '{% include "_sleep_panel.html" %}' in sections
    assert sections.index("_entity_care.html") < sections.index("_affect_welfare.html")
    assert sections.index("_affect_welfare.html") < sections.index("_sleep_panel.html")
    base = (TEMPLATE_DIR / "_base.html").read_text(encoding="utf-8")
    assert "/static/dashboard_sleep.js" in base


_DRIVES = ("boredom", "social_drive", "restlessness")


def _record(**overrides):
    record = {
        "ts": "2026-01-02T12:00:00+00:00",
        "current_run": True,
        "awake_seconds": 7200.0,
        "negative_valence_bar": 0.5,
        "negative_valence_share": 0.125,
        "curiosity_interest_share": 0.4,
    }
    for drive in _DRIVES:
        record[f"{drive}_uncontrolled_share"] = 0.5
        record[f"{drive}_uncontrolled_per_awake_hour"] = 1.5
        record[f"{drive}_deprivation_share"] = 0.1
        record[f"{drive}_sleep_reset_ends"] = 2
        record[f"{drive}_open_crossings"] = 0
    record.update(overrides)
    return record


def _render(welfare):
    template = _templates().env.get_template("_affect_welfare.html")
    return template.render(welfare=welfare)


def test_affect_welfare_full_record():
    html = _render(
        {
            "affect_welfare": _record(
                boredom_uncontrolled_share=0.25,
                boredom_open_crossings=1,
                social_drive_uncontrolled_share=None,
                social_drive_open_crossings=None,
            )
        }
    )
    assert 'id="affect-welfare"' in html
    assert "affect welfare record (read-only)" in html
    assert "25.0%" in html
    assert "yes" in html
    assert "n/a" in html
    assert "2.0 h" in html
    assert "12.5%" in html
    assert "1.50" in html
    assert "40.0%" in html
    assert "social drive" in html
    assert "From before the welfare observer" not in html
    assert chr(0x2014) not in html


def test_affect_welfare_not_current_run_shows_note():
    html = _render({"affect_welfare": _record(current_run=False)})
    assert "From before the welfare observer's latest start." in html


def test_affect_welfare_none_shows_empty_text():
    for welfare in ({"affect_welfare": None}, None, {}):
        html = _render(welfare)
        assert "No affect welfare record yet." in html
        assert "every 300 s of unfrozen time" in html


class StubBus:
    async def read(self, stream, *, last_id, count, block_ms):
        return []

    async def current_workspace_id(self):
        return "0"


@pytest.mark.asyncio
async def test_console_page_has_welfare_panels():
    config = DashboardConfig(
        conversation_enabled=True,
        diagnostics_enabled=True,
        host_allowlist=("127.0.0.1", "localhost", "test"),
        operator_token="test-token",
    )
    bridge = BusBridge(StubBus(), PrivacyFilter(), streams=[], poll_interval_s=0.01)

    async def history_loader(n: int):
        return []

    app = create_app(
        config=config,
        bridge=bridge,
        history_loader=history_loader,
        metrics_snapshot=lambda: {"cycle_status": "not running"},
        conversation_state=ConversationState(),
    )
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )
    try:
        resp = await client.get("/", headers={"Authorization": "Bearer test-token"})
        assert resp.status_code == 200
        assert 'id="sleep-rest"' in resp.text
        assert 'id="affect-welfare"' in resp.text
        assert "dashboard_sleep.js" in resp.text
    finally:
        await client.aclose()
