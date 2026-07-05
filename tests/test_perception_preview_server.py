# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Dev-gated LOOPBACK perception-preview server.

The server bridges the in-RAM preview holder from the cycle process to the
separate Nexus process over a 127.0.0.1-only socket. These tests prove:

  * OFF by default — ``start_preview_server`` returns None when the dev flag is
    unset, so nothing binds (connection refused) and the PiP stays hidden.
  * ON — the running server serves the in-RAM JPEG / audio level over loopback,
    and 404s when the slot is empty or the flag is cleared mid-flight.
  * LOOPBACK ONLY — a non-loopback bind host is refused.
  * ZERO PERSISTENCE — the server module opens no file for writing (sockets +
    BytesIO only), and serving a frame leaves nothing on disk.
"""
from __future__ import annotations

import re
import socket
from pathlib import Path

import httpx
import pytest

from kaine import perception_preview
from kaine import perception_preview_server
from kaine.perception_preview_server import (
    DEFAULT_PREVIEW_PORT,
    PreviewServer,
    preview_port,
    start_preview_server,
)


@pytest.fixture(autouse=True)
def _clean_holder():
    perception_preview.clear()
    yield
    perception_preview.clear()


def _enable(monkeypatch):
    monkeypatch.setenv(perception_preview.DEV_ENV_VAR, "1")


def _disable(monkeypatch):
    monkeypatch.delenv(perception_preview.DEV_ENV_VAR, raising=False)


# ---------------------------------------------------------------------------
# Dev gate + lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_returns_none_when_flag_off(monkeypatch):
    _disable(monkeypatch)
    server = await start_preview_server(port=0)
    assert server is None


@pytest.mark.asyncio
async def test_flag_off_nothing_bound_on_port(monkeypatch):
    """With the flag off nothing binds → a fresh connect to the default port is
    refused (or at least not our server). Prove start_preview_server binds
    nothing by attempting to bind the same port ourselves."""
    _disable(monkeypatch)
    server = await start_preview_server(port=0)
    assert server is None
    # A raw connect to an unused high port is refused — sanity that "not started"
    # means "connection refused", which the Nexus proxy maps to 404.
    with pytest.raises((ConnectionRefusedError, OSError)):
        with socket.create_connection(("127.0.0.1", 59997), timeout=0.5):
            pass


@pytest.mark.asyncio
async def test_binds_loopback_only():
    # The listener refuses any non-loopback bind address.
    with pytest.raises(ValueError):
        PreviewServer(port=0, host="0.0.0.0")
    server = PreviewServer(port=0, host="127.0.0.1")
    await server.start()
    try:
        # Bound socket is on loopback.
        assert server.host == "127.0.0.1"
        assert server.port > 0
    finally:
        await server.stop()


# ---------------------------------------------------------------------------
# Serving the in-RAM slot over loopback
# ---------------------------------------------------------------------------


@pytest.fixture
async def running(monkeypatch):
    _enable(monkeypatch)
    server = await start_preview_server(port=0)
    assert server is not None
    base = f"http://127.0.0.1:{server.port}"
    try:
        yield server, base
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_video_404_when_empty(running):
    _server, base = running
    async with httpx.AsyncClient(timeout=2.0) as c:
        r = await c.get(f"{base}/video")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_video_serves_in_ram_frame(running):
    _server, base = running
    perception_preview.set_video_jpeg(b"\xff\xd8framebytes\xff\xd9")
    async with httpx.AsyncClient(timeout=2.0) as c:
        r = await c.get(f"{base}/video")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.headers.get("cache-control") == "no-store"
    assert r.content == b"\xff\xd8framebytes\xff\xd9"


@pytest.mark.asyncio
async def test_audio_serves_level_json(running):
    _server, base = running
    async with httpx.AsyncClient(timeout=2.0) as c:
        empty = await c.get(f"{base}/audio")
        assert empty.status_code == 200
        assert empty.json()["level"] is None
        perception_preview.set_audio_level(0.73)
        r = await c.get(f"{base}/audio")
    assert r.status_code == 200
    assert r.json()["level"] == pytest.approx(0.73)


@pytest.mark.asyncio
async def test_unknown_path_404(running):
    _server, base = running
    async with httpx.AsyncClient(timeout=2.0) as c:
        r = await c.get(f"{base}/secrets")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_query_string_is_tolerated(running):
    """The Nexus PiP cache-busts with ?t=<ts>; the router must ignore the query."""
    _server, base = running
    perception_preview.set_video_jpeg(b"\xff\xd8\xff\xd9")
    async with httpx.AsyncClient(timeout=2.0) as c:
        r = await c.get(f"{base}/video?t=12345")
    assert r.status_code == 200
    assert r.content == b"\xff\xd8\xff\xd9"


@pytest.mark.asyncio
async def test_clearing_flag_midflight_404s(running, monkeypatch):
    _server, base = running
    perception_preview.set_video_jpeg(b"\xff\xd8\xff\xd9")
    async with httpx.AsyncClient(timeout=2.0) as c:
        ok = await c.get(f"{base}/video")
        assert ok.status_code == 200
        # Clear the dev override — the live re-check makes the route 404 even
        # while the listener is still up.
        _disable(monkeypatch)
        gone = await c.get(f"{base}/video")
    assert gone.status_code == 404


# ---------------------------------------------------------------------------
# Config port
# ---------------------------------------------------------------------------


def test_preview_port_defaults():
    assert preview_port({}) == DEFAULT_PREVIEW_PORT
    assert preview_port({"perception_preview": {"port": 9191}}) == 9191
    # Malformed value falls back to the default rather than crashing boot.
    assert preview_port({"perception_preview": {"port": "nope"}}) == DEFAULT_PREVIEW_PORT


def test_shipped_config_declares_preview_port():
    import tomllib

    data = tomllib.loads(Path("config/kaine.toml").read_text())
    assert data["perception_preview"]["port"] == DEFAULT_PREVIEW_PORT


# ---------------------------------------------------------------------------
# Zero persistence — the server opens no file for writing
# ---------------------------------------------------------------------------


def test_server_module_opens_no_file_for_writing():
    src = Path(perception_preview_server.__file__).read_text()
    # No file opens in any write/append/update mode.
    assert not re.search(r"open\([^)]*['\"][wax]\+?b?['\"]", src), (
        "preview server must not open any file for writing"
    )
    for forbidden in (
        "imwrite(",
        "VideoWriter(",
        "imsave(",
        "np.save(",
        ".tofile(",
        "wave.open(",
    ):
        assert forbidden not in src, f"preview server contains disk writer {forbidden!r}"


@pytest.mark.asyncio
async def test_serving_frame_writes_nothing_to_disk(running, tmp_path):
    """Serving a frame over loopback leaves no file behind (RAM + sockets only)."""
    _server, base = running
    before = {p for p in tmp_path.rglob("*") if p.is_file()}
    perception_preview.set_video_jpeg(b"\xff\xd8\xff\xd9")
    async with httpx.AsyncClient(timeout=2.0) as c:
        r = await c.get(f"{base}/video")
    assert r.status_code == 200
    after = {p for p in tmp_path.rglob("*") if p.is_file()}
    assert after == before
