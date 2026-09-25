# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the Nexus caretaker acknowledge router."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
from fastapi import Depends, FastAPI

from kaine.cycle.caretaker_state import CaretakerStart, read_ack, write_start
from kaine.nexus.auth import require_operator_token
from kaine.nexus.caretaker import build_caretaker_router
from kaine.nexus.config import NexusConfig


def _isolated_router(tmp_path):
    start_path = tmp_path / "caretaker_start.json"
    ack_path = tmp_path / "caretaker_ack.json"
    app = FastAPI()
    app.state.config = NexusConfig(
        operator_token="test-token",
        host_allowlist=("127.0.0.1", "localhost", "t"),
    )
    app.include_router(
        build_caretaker_router(start_path=start_path, ack_path=ack_path),
        dependencies=[Depends(require_operator_token)],
    )
    return app, start_path, ack_path


@pytest.mark.asyncio
async def test_get_unauthorized(tmp_path):
    app, _, _ = _isolated_router(tmp_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/diagnostics/caretaker.json")
    assert r.status_code != 200


@pytest.mark.asyncio
async def test_get_no_start_returns_pending_false(tmp_path):
    app, _, _ = _isolated_router(tmp_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get(
            "/diagnostics/caretaker.json",
            headers={"Authorization": "Bearer test-token"},
        )
    assert r.status_code == 200
    data = r.json()
    assert data["pending"] is False
    assert data["start_id"] is None
    assert data["started_at"] is None
    assert data["acknowledged_at"] is None
    assert r.headers.get("cache-control") == "no-store"


@pytest.mark.asyncio
async def test_get_with_start_returns_pending_true(tmp_path):
    app, start_path, _ = _isolated_router(tmp_path)
    start_id = "a" * 32
    started_at = datetime.now(timezone.utc).isoformat()
    write_start(
        CaretakerStart(start_id=start_id, started_at=started_at),
        path=start_path,
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get(
            "/diagnostics/caretaker.json",
            headers={"Authorization": "Bearer test-token"},
        )
    assert r.status_code == 200
    data = r.json()
    assert data["pending"] is True
    assert data["start_id"] == start_id
    assert data["started_at"] == started_at
    assert data["acknowledged_at"] is None


@pytest.mark.asyncio
async def test_post_ack_writes_ack_and_preserves_start(tmp_path):
    app, start_path, ack_path = _isolated_router(tmp_path)
    start_id = "a" * 32
    started_at = datetime.now(timezone.utc).isoformat()
    write_start(
        CaretakerStart(start_id=start_id, started_at=started_at),
        path=start_path,
    )
    start_bytes = start_path.read_bytes()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post(
            "/diagnostics/caretaker/ack",
            json={"start_id": start_id},
            headers={"Authorization": "Bearer test-token"},
        )
    assert r.status_code == 200
    data = r.json()
    assert data["pending"] is False
    assert data["start_id"] == start_id
    assert data["started_at"] == started_at
    assert data["acknowledged_at"] is not None

    ack = read_ack(ack_path)
    assert ack is not None
    assert ack.start_id == start_id
    assert ack.acknowledged_at is not None

    assert start_path.read_bytes() == start_bytes
    assert r.headers.get("cache-control") == "no-store"


@pytest.mark.asyncio
async def test_post_ack_wrong_id_rejected(tmp_path):
    app, start_path, ack_path = _isolated_router(tmp_path)
    start_id = "a" * 32
    write_start(
        CaretakerStart(
            start_id=start_id,
            started_at=datetime.now(timezone.utc).isoformat(),
        ),
        path=start_path,
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post(
            "/diagnostics/caretaker/ack",
            json={"start_id": "b" * 32},
            headers={"Authorization": "Bearer test-token"},
        )
    assert r.status_code == 409
    assert (
        r.json()["detail"] == "start_id does not match the current unattended start"
    )
    assert not ack_path.exists()


@pytest.mark.asyncio
async def test_post_ack_malformed_id_rejected(tmp_path):
    app, _, _ = _isolated_router(tmp_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post(
            "/diagnostics/caretaker/ack",
            json={"start_id": "x"},
            headers={"Authorization": "Bearer test-token"},
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_ack_no_start_rejected(tmp_path):
    app, _, ack_path = _isolated_router(tmp_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post(
            "/diagnostics/caretaker/ack",
            json={"start_id": "a" * 32},
            headers={"Authorization": "Bearer test-token"},
        )
    assert r.status_code == 409
    assert r.json()["detail"] == "no unattended start to acknowledge"
    assert not ack_path.exists()


@pytest.mark.asyncio
async def test_post_ack_unauthorized(tmp_path):
    app, start_path, ack_path = _isolated_router(tmp_path)
    start_id = "a" * 32
    write_start(
        CaretakerStart(
            start_id=start_id,
            started_at=datetime.now(timezone.utc).isoformat(),
        ),
        path=start_path,
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post(
            "/diagnostics/caretaker/ack",
            json={"start_id": start_id},
        )
    assert r.status_code != 200
    assert not ack_path.exists()


@pytest.mark.asyncio
async def test_post_ack_idempotent(tmp_path):
    app, start_path, ack_path = _isolated_router(tmp_path)
    start_id = "a" * 32
    write_start(
        CaretakerStart(
            start_id=start_id,
            started_at=datetime.now(timezone.utc).isoformat(),
        ),
        path=start_path,
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r1 = await c.post(
            "/diagnostics/caretaker/ack",
            json={"start_id": start_id},
            headers={"Authorization": "Bearer test-token"},
        )
        r2 = await c.post(
            "/diagnostics/caretaker/ack",
            json={"start_id": start_id},
            headers={"Authorization": "Bearer test-token"},
        )
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["pending"] is False
    assert r2.json()["pending"] is False
    ack = read_ack(ack_path)
    assert ack is not None
    assert ack.start_id == start_id
