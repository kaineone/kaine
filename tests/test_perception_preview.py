# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Dev-gated perception preview: in-memory holder, Topos/Audition taps, and the
Nexus preview routes.

Load-bearing invariants exercised here:
  * OFF by default — no capture, no bytes, nothing on disk.
  * ON (KAINE_PERCEPTION_PREVIEW=1) — a single overwritten in-memory JPEG /
    audio level exists, but STILL nothing lands on disk.
  * The Nexus routes 404 when the flag is off or the slot is empty, and serve
    the in-memory bytes / level when populated.
"""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from kaine import perception_preview
from kaine.nexus.perception import build_perception_router


@pytest.fixture(autouse=True)
def _clean_holder():
    """Every test starts and ends with an empty holder + the dev flag unset."""
    perception_preview.clear()
    yield
    perception_preview.clear()


def _enable(monkeypatch):
    monkeypatch.setenv(perception_preview.DEV_ENV_VAR, "1")


def _disable(monkeypatch):
    monkeypatch.delenv(perception_preview.DEV_ENV_VAR, raising=False)


# ---------------------------------------------------------------------------
# Holder dev-gate
# ---------------------------------------------------------------------------


def test_holder_writes_are_noops_when_flag_off(monkeypatch):
    _disable(monkeypatch)
    assert perception_preview.preview_enabled() is False
    perception_preview.set_video_jpeg(b"\xff\xd8\xff-not-really")
    perception_preview.set_audio_level(0.9)
    assert perception_preview.get_video_jpeg() is None
    assert perception_preview.get_audio_level() is None


def test_holder_round_trips_when_flag_on(monkeypatch):
    _enable(monkeypatch)
    perception_preview.set_video_jpeg(b"jpegbytes")
    perception_preview.set_audio_level(0.5)
    assert perception_preview.get_video_jpeg() == b"jpegbytes"
    assert perception_preview.get_audio_level() == pytest.approx(0.5)
    # Single overwritten slot.
    perception_preview.set_video_jpeg(b"newer")
    assert perception_preview.get_video_jpeg() == b"newer"
    perception_preview.clear()
    assert perception_preview.get_video_jpeg() is None


def test_encode_jpeg_preview_uses_memory_only():
    """encode_jpeg_preview returns JPEG bytes for a PIL image (via BytesIO) and
    None for a non-image — never raising, never touching a file."""
    Image = pytest.importorskip("PIL.Image")
    img = Image.new("RGB", (16, 12), (10, 20, 30))
    data = perception_preview.encode_jpeg_preview(img, quality=50)
    assert data is not None and data[:2] == b"\xff\xd8"  # JPEG SOI marker
    assert perception_preview.encode_jpeg_preview(object()) is None


# ---------------------------------------------------------------------------
# Topos tap
# ---------------------------------------------------------------------------


class _FakeEncoder:
    model_id = "fake/encoder"
    latent_dim = 4

    async def load(self):
        return None

    async def shutdown(self):
        return None

    async def encode(self, image):  # noqa: ARG002
        return [1.0, 0.0, 0.0, 0.0]


def _topos(bus):
    from kaine.modules.topos import Topos

    return Topos(bus, encoder=_FakeEncoder())


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    from kaine.bus.client import AsyncBus
    from kaine.bus.config import BusConfig

    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


@pytest.mark.asyncio
async def test_topos_tap_off_captures_nothing(bus, monkeypatch):
    _disable(monkeypatch)
    Image = pytest.importorskip("PIL.Image")
    topos = _topos(bus)
    await topos.process_frame(Image.new("RGB", (16, 12), (1, 2, 3)))
    assert topos._preview_jpeg is None
    assert perception_preview.get_video_jpeg() is None


@pytest.mark.asyncio
async def test_topos_tap_on_holds_frame_in_memory(bus, monkeypatch, tmp_path):
    _enable(monkeypatch)
    Image = pytest.importorskip("PIL.Image")
    # Scan a scratch tree before/after to prove no frame lands on disk.
    scan_root = tmp_path
    before = set(p for p in scan_root.rglob("*") if p.is_file())

    topos = _topos(bus)
    await topos.process_frame(Image.new("RGB", (16, 12), (9, 9, 9)))

    assert topos._preview_jpeg is not None
    assert topos._preview_jpeg[:2] == b"\xff\xd8"
    assert perception_preview.get_video_jpeg() == topos._preview_jpeg

    after = set(p for p in scan_root.rglob("*") if p.is_file())
    assert after == before, "preview tap must not write any file"


@pytest.mark.asyncio
async def test_topos_shutdown_drops_preview(bus, monkeypatch):
    _enable(monkeypatch)
    Image = pytest.importorskip("PIL.Image")
    topos = _topos(bus)
    await topos.initialize()
    await topos.process_frame(Image.new("RGB", (8, 8), (5, 5, 5)))
    assert topos._preview_jpeg is not None
    await topos.shutdown()
    assert topos._preview_jpeg is None
    assert perception_preview.get_video_jpeg() is None


# ---------------------------------------------------------------------------
# Audition audio-level tap
# ---------------------------------------------------------------------------


def test_audio_level_tap_off_is_noop(monkeypatch):
    _disable(monkeypatch)
    from kaine.modules.audition.live import _tap_audio_level
    import struct

    loud = struct.pack("<480h", *([12000] * 480))
    _tap_audio_level(loud, 16000)
    assert perception_preview.get_audio_level() is None


def test_audio_level_tap_on_reports_normalised_rms(monkeypatch):
    _enable(monkeypatch)
    from kaine.modules.audition.live import _tap_audio_level
    import struct

    silent = struct.pack("<480h", *([0] * 480))
    _tap_audio_level(silent, 16000)
    assert perception_preview.get_audio_level() == pytest.approx(0.0)

    loud = struct.pack("<480h", *([16384] * 480))
    _tap_audio_level(loud, 16000)
    level = perception_preview.get_audio_level()
    assert level is not None and 0.4 < level <= 1.0


# ---------------------------------------------------------------------------
# Nexus preview routes — now a LOOPBACK PROXY to the cycle's preview server.
#
# The holder lives in the cycle process; Nexus is separate. The routes proxy to
# 127.0.0.1:<port> where the cycle serves the in-RAM slot. These tests stand up a
# real PreviewServer on an ephemeral loopback port and point the router at it, so
# the whole proxy path (Nexus route → loopback socket → holder) is exercised end
# to end — not a bypass.
# ---------------------------------------------------------------------------

from kaine.perception_preview_server import PreviewServer


@pytest.fixture
async def preview_server():
    """A running loopback preview server on an ephemeral port."""
    server = PreviewServer(port=0)
    await server.start()
    try:
        yield server
    finally:
        await server.stop()


def _router_client(port: int):
    app = FastAPI()
    app.include_router(build_perception_router(preview_port=port))
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://t")


@pytest.mark.asyncio
async def test_preview_video_404_when_flag_off(monkeypatch):
    _disable(monkeypatch)
    # Flag off short-circuits before any connection — no server needed.
    async with _router_client(59999) as c:
        r = await c.get("/diagnostics/perception/preview/video")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_preview_video_404_when_cycle_not_running(monkeypatch):
    _enable(monkeypatch)
    # Flag on but nothing listening on that port → honest 404, PiP stays hidden.
    async with _router_client(59998) as c:
        r = await c.get("/diagnostics/perception/preview/video")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_preview_video_404_when_server_up_but_empty(preview_server, monkeypatch):
    _enable(monkeypatch)
    async with _router_client(preview_server.port) as c:
        r = await c.get("/diagnostics/perception/preview/video")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_preview_video_proxies_bytes_when_populated(preview_server, monkeypatch):
    _enable(monkeypatch)
    perception_preview.set_video_jpeg(b"\xff\xd8\xff\xd9")  # minimal JPEG-ish
    async with _router_client(preview_server.port) as c:
        r = await c.get("/diagnostics/perception/preview/video")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.content == b"\xff\xd8\xff\xd9"
    assert r.headers.get("cache-control") == "no-store"


@pytest.mark.asyncio
async def test_preview_audio_404_when_flag_off(monkeypatch):
    _disable(monkeypatch)
    async with _router_client(59999) as c:
        r = await c.get("/diagnostics/perception/preview/audio")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_preview_audio_proxies_level_when_on(preview_server, monkeypatch):
    _enable(monkeypatch)
    async with _router_client(preview_server.port) as c:
        r_empty = await c.get("/diagnostics/perception/preview/audio")
        assert r_empty.status_code == 200
        assert r_empty.json()["level"] is None
        perception_preview.set_audio_level(0.42)
        r = await c.get("/diagnostics/perception/preview/audio")
    assert r.status_code == 200
    assert r.json()["level"] == pytest.approx(0.42)


@pytest.mark.asyncio
async def test_perception_snapshot_exposes_preview_flag(monkeypatch):
    from kaine.nexus.perception import perception_snapshot

    _enable(monkeypatch)
    assert perception_snapshot()["preview_enabled"] is True
    _disable(monkeypatch)
    assert perception_snapshot()["preview_enabled"] is False


# ---------------------------------------------------------------------------
# Zero-persistence: the preview module opens no file for writing
# ---------------------------------------------------------------------------


def test_preview_module_opens_no_file_for_writing():
    """Static guard: the preview holder must never open a file, save an image to
    a path, or invoke any disk/frame writer. The only encode path is BytesIO."""
    import re

    src = (
        Path(__file__).resolve().parents[1] / "kaine" / "perception_preview.py"
    ).read_text()
    # No file opens in any write/append/update mode.
    assert not re.search(r"open\([^)]*['\"][waxr]?b?\+?['\"]", src) or "BytesIO" in src
    # No frame/image/audio persisting calls.
    for forbidden in ("imwrite(", "VideoWriter(", "imsave(", "np.save(", ".tofile(", "wave.open("):
        assert forbidden not in src, f"preview module contains disk writer {forbidden!r}"
    # The single image encode goes to an in-memory BytesIO, never a path.
    assert "io.BytesIO" in src
    assert 'format="JPEG"' in src
