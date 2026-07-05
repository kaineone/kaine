# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for kaine.modules.hypnos.hot_swap dispatcher modes."""
from __future__ import annotations

from pathlib import Path

import pytest

from kaine.modules.hypnos.hot_swap import MANUAL_MARKER, VALID_MODES, dispatch


@pytest.mark.asyncio
async def test_manual_mode_writes_marker(tmp_path: Path):
    out = tmp_path / "adapters"
    out.mkdir()
    adapter = out / "20260530T120000"
    adapter.mkdir()
    result = await dispatch(
        mode="manual",
        adapter_output_dir=out,
        adapter_path=adapter,
    )
    assert result["ok"] is True
    marker = out / MANUAL_MARKER
    assert marker.exists()
    assert str(adapter) in marker.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_manual_mode_overwrites_existing_marker(tmp_path: Path):
    out = tmp_path / "adapters"
    out.mkdir()
    (out / MANUAL_MARKER).write_text("/old/path\n", encoding="utf-8")
    adapter = out / "20260530T130000"
    adapter.mkdir()
    await dispatch(mode="manual", adapter_output_dir=out, adapter_path=adapter)
    contents = (out / MANUAL_MARKER).read_text(encoding="utf-8")
    assert "/old/path" not in contents
    assert str(adapter) in contents


@pytest.mark.asyncio
async def test_reload_endpoint_posts_to_url(tmp_path: Path):
    out = tmp_path / "adapters"
    out.mkdir()
    adapter = out / "20260530T120000"
    adapter.mkdir()
    posted: list[tuple[str, dict]] = []

    async def fake_poster(url: str, body: dict) -> None:
        posted.append((url, body))

    result = await dispatch(
        mode="reload_endpoint",
        adapter_output_dir=out,
        adapter_path=adapter,
        reload_endpoint_url="http://127.0.0.1:11434/v1/internal/reload",
        http_poster=fake_poster,
    )
    assert result["ok"] is True
    assert len(posted) == 1
    url, body = posted[0]
    assert url == "http://127.0.0.1:11434/v1/internal/reload"
    assert body == {"adapter_path": str(adapter)}


@pytest.mark.asyncio
async def test_reload_endpoint_fails_when_url_missing(tmp_path: Path):
    out = tmp_path / "adapters"
    out.mkdir()
    adapter = out / "20260530T120000"
    adapter.mkdir()
    result = await dispatch(
        mode="reload_endpoint",
        adapter_output_dir=out,
        adapter_path=adapter,
    )
    assert result["ok"] is False
    assert "reload_endpoint_url not configured" in result["error"]


@pytest.mark.asyncio
async def test_reload_endpoint_swallows_post_errors(tmp_path: Path):
    out = tmp_path / "adapters"
    out.mkdir()
    adapter = out / "20260530T120000"
    adapter.mkdir()

    async def boom(url: str, body: dict) -> None:
        raise RuntimeError("connection refused")

    # Use a loopback URL so the privacy guard passes; the POST itself fails.
    result = await dispatch(
        mode="reload_endpoint",
        adapter_output_dir=out,
        adapter_path=adapter,
        reload_endpoint_url="http://127.0.0.1:9999/",
        http_poster=boom,
    )
    assert result["ok"] is False
    assert "RuntimeError" in result["error"]


@pytest.mark.asyncio
async def test_restart_service_invokes_systemctl(tmp_path: Path):
    out = tmp_path / "adapters"
    out.mkdir()
    adapter = out / "20260530T120000"
    adapter.mkdir()
    invoked: list[list[str]] = []

    async def fake_runner(cmd: list[str]) -> int:
        invoked.append(cmd)
        return 0

    result = await dispatch(
        mode="restart_service",
        adapter_output_dir=out,
        adapter_path=adapter,
        restart_service_unit="unsloth-studio.service",
        service_runner=fake_runner,
    )
    assert result["ok"] is True
    assert invoked == [["systemctl", "--user", "restart", "unsloth-studio.service"]]


@pytest.mark.asyncio
async def test_restart_service_fails_when_unit_missing(tmp_path: Path):
    out = tmp_path / "adapters"
    out.mkdir()
    adapter = out / "20260530T120000"
    adapter.mkdir()
    result = await dispatch(
        mode="restart_service",
        adapter_output_dir=out,
        adapter_path=adapter,
    )
    assert result["ok"] is False
    assert "restart_service_unit not configured" in result["error"]


@pytest.mark.asyncio
async def test_restart_service_reports_nonzero_rc(tmp_path: Path):
    out = tmp_path / "adapters"
    out.mkdir()
    adapter = out / "20260530T120000"
    adapter.mkdir()

    async def fake_runner(cmd: list[str]) -> int:
        return 3

    result = await dispatch(
        mode="restart_service",
        adapter_output_dir=out,
        adapter_path=adapter,
        restart_service_unit="bad.service",
        service_runner=fake_runner,
    )
    assert result["ok"] is False
    assert result["rc"] == 3


@pytest.mark.asyncio
async def test_unknown_mode_does_not_raise(tmp_path: Path):
    out = tmp_path / "adapters"
    out.mkdir()
    adapter = out / "20260530T120000"
    adapter.mkdir()
    result = await dispatch(
        mode="nonsense",
        adapter_output_dir=out,
        adapter_path=adapter,
    )
    assert result["ok"] is False
    assert result["error"] == "unknown mode"


def test_valid_modes_constant_matches_implementation():
    assert "manual" in VALID_MODES
    assert "reload_endpoint" in VALID_MODES
    assert "restart_service" in VALID_MODES
