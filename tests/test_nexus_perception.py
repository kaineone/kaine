# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Nexus perception router: GET .json + POST toggle.

Renders the banner partial when state shows active. Privacy filter
covered separately in tests/test_nexus_privacy.py — restated here:
transcription text never reaches the diagnostics SSE."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from kaine import perception_state
from kaine.bus.schema import Event
from kaine.nexus.perception import (
    build_perception_router,
    perception_snapshot,
)
from kaine.nexus.privacy import PrivacyFilter


def _isolated_router(tmp_path):
    runtime = tmp_path / "runtime.json"
    desired = tmp_path / "desired.json"
    app = FastAPI()
    app.include_router(
        build_perception_router(runtime_path=runtime, desired_path=desired)
    )
    return app, runtime, desired


@pytest.mark.asyncio
async def test_perception_json_returns_default_state(tmp_path):
    app, _, _ = _isolated_router(tmp_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/diagnostics/perception.json")
    assert r.status_code == 200
    data = r.json()
    assert data["audio_live_active"] is False
    assert data["video_live_active"] is False
    assert "audio_available" in data
    assert "video_available" in data


@pytest.mark.asyncio
async def test_toggle_audio_writes_desired_file(tmp_path):
    app, runtime, desired = _isolated_router(tmp_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post(
            "/diagnostics/perception/toggle",
            json={"surface": "audio", "active": True},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["audio_live_desired"] is True
    # File on disk reflects the toggle.
    on_disk = perception_state.read_desired(desired)
    assert on_disk.audio_live_desired is True


@pytest.mark.asyncio
async def test_toggle_rejects_unknown_surface(tmp_path):
    app, _, _ = _isolated_router(tmp_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post(
            "/diagnostics/perception/toggle",
            json={"surface": "olfactory", "active": True},
        )
    assert r.status_code == 422  # FastAPI validation error


def test_perception_snapshot_includes_availability():
    snap = perception_snapshot()
    assert "audio_available" in snap
    assert "video_available" in snap
    assert "audio_live_active" in snap


def test_privacy_filter_strips_transcription_for_diagnostics():
    """Restate the existing privacy invariant for the new event source:
    a transcription event flowing from LiveMicrophone is content-stripped
    before reaching diagnostics SSE."""
    pf = PrivacyFilter()
    ev = Event(
        source="audition",
        type="audition.transcription",
        payload={"text": "secret words", "source_label": "live_mic"},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )
    out = pf.filter(ev, surface="diagnostics")
    assert "text" not in out.payload
    assert out.payload.get("source_label") == "live_mic"


def test_banner_partial_renders_when_audio_active(tmp_path):
    """Render the conversation page; banner appears when audio is active."""
    from fastapi.templating import Jinja2Templates
    from kaine.nexus.conversation import _templates as conv_templates

    templates = conv_templates()
    # Use the partial directly — pass a perception dict.
    out = templates.get_template("_perception_banner.html").render(
        perception={
            "audio_live_active": True,
            "video_live_active": False,
        }
    )
    assert "microphone on" in out
    assert "live-perception-banner" in out


def test_banner_partial_absent_when_nothing_active():
    from kaine.nexus.conversation import _templates as conv_templates

    out = conv_templates().get_template("_perception_banner.html").render(
        perception={"audio_live_active": False, "video_live_active": False}
    )
    assert "microphone on" not in out
    assert "camera on" not in out


@pytest.mark.asyncio
async def test_perception_json_includes_locus_default(tmp_path):
    app, _, _ = _isolated_router(tmp_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        data = (await c.get("/diagnostics/perception.json")).json()
    assert data["locus"] == "physical"
    assert data["locus_locked"] is False


@pytest.mark.asyncio
async def test_set_locus_writes_desired_and_validates(tmp_path):
    app, _, desired = _isolated_router(tmp_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post(
            "/diagnostics/perception/locus",
            json={"locus": "virtual", "locked": True},
        )
        assert r.status_code == 200
        assert r.json() == {"locus": "virtual", "locus_locked": True}
        # reflected in the snapshot + on disk
        g = (await c.get("/diagnostics/perception.json")).json()
        assert g["locus"] == "virtual" and g["locus_locked"] is True
        assert perception_state.read_desired(desired).locus == "virtual"
        # invalid locus rejected
        bad = await c.post("/diagnostics/perception/locus", json={"locus": "narnia"})
        assert bad.status_code == 422
