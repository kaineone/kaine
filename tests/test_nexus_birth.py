# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the Nexus birth acknowledgement router."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
from fastapi import Depends, FastAPI

from kaine.lifecycle.birth_ack import BirthRequest, read_ack, write_request
from kaine.nexus.auth import require_operator_token
from kaine.nexus.birth import build_birth_router
from kaine.nexus.config import NexusConfig


def _isolated_router(tmp_path):
    request_path = tmp_path / "birth_request.json"
    ack_path = tmp_path / "birth_ack.json"
    stage_path = tmp_path / "stage.json"
    app = FastAPI()
    app.state.config = NexusConfig(
        operator_token="test-token",
        host_allowlist=("127.0.0.1", "localhost", "t"),
    )
    app.include_router(
        build_birth_router(request_path=request_path, ack_path=ack_path),
        dependencies=[Depends(require_operator_token)],
    )
    return app, request_path, ack_path, stage_path


@pytest.mark.asyncio
async def test_get_unauthorized(tmp_path):
    app, _, _, stage_path = _isolated_router(tmp_path)
    stage_path.write_bytes(b"stage")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/diagnostics/birth.json")
    assert r.status_code != 200
    assert stage_path.read_bytes() == b"stage"


@pytest.mark.asyncio
async def test_get_no_request_returns_pending_false(tmp_path):
    app, request_path, ack_path, stage_path = _isolated_router(tmp_path)
    stage_path.write_bytes(b"stage")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get(
            "/diagnostics/birth.json",
            headers={"Authorization": "Bearer test-token"},
        )
    assert r.status_code == 200
    data = r.json()
    assert data["pending"] is False
    assert data["request_id"] is None
    assert data["requested_at"] is None
    assert data["acknowledged_at"] is None
    assert r.headers.get("cache-control") == "no-store"
    assert not request_path.exists()
    assert not ack_path.exists()
    assert stage_path.read_bytes() == b"stage"


@pytest.mark.asyncio
async def test_get_with_request_returns_pending_true(tmp_path):
    app, request_path, _, stage_path = _isolated_router(tmp_path)
    stage_path.write_bytes(b"stage")
    request_id = "a" * 32
    requested_at = datetime.now(timezone.utc).isoformat()
    write_request(
        BirthRequest(
            request_id=request_id,
            requested_at=requested_at,
            gestation_started_at=None,
        ),
        path=request_path,
    )
    request_bytes = request_path.read_bytes()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get(
            "/diagnostics/birth.json",
            headers={"Authorization": "Bearer test-token"},
        )
    assert r.status_code == 200
    data = r.json()
    assert data["pending"] is True
    assert data["request_id"] == request_id
    assert data["requested_at"] == requested_at
    assert data["acknowledged_at"] is None
    assert request_path.read_bytes() == request_bytes
    assert stage_path.read_bytes() == b"stage"


@pytest.mark.asyncio
async def test_post_ack_writes_ack_and_preserves_request(tmp_path):
    app, request_path, ack_path, stage_path = _isolated_router(tmp_path)
    stage_path.write_bytes(b"stage")
    request_id = "a" * 32
    requested_at = datetime.now(timezone.utc).isoformat()
    write_request(
        BirthRequest(
            request_id=request_id,
            requested_at=requested_at,
            gestation_started_at=None,
        ),
        path=request_path,
    )
    request_bytes = request_path.read_bytes()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post(
            "/diagnostics/birth/ack",
            json={"request_id": request_id},
            headers={"Authorization": "Bearer test-token"},
        )
    assert r.status_code == 200
    data = r.json()
    assert data["pending"] is False
    assert data["request_id"] == request_id
    assert data["requested_at"] == requested_at
    assert data["acknowledged_at"] is not None

    ack = read_ack(ack_path)
    assert ack is not None
    assert ack.request_id == request_id
    assert ack.acknowledged_at is not None

    assert request_path.read_bytes() == request_bytes
    assert stage_path.read_bytes() == b"stage"
    assert r.headers.get("cache-control") == "no-store"


@pytest.mark.asyncio
async def test_post_ack_wrong_id_rejected(tmp_path):
    app, request_path, ack_path, stage_path = _isolated_router(tmp_path)
    stage_path.write_bytes(b"stage")
    request_id = "a" * 32
    write_request(
        BirthRequest(
            request_id=request_id,
            requested_at=datetime.now(timezone.utc).isoformat(),
            gestation_started_at=None,
        ),
        path=request_path,
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post(
            "/diagnostics/birth/ack",
            json={"request_id": "b" * 32},
            headers={"Authorization": "Bearer test-token"},
        )
    assert r.status_code == 409
    assert (
        r.json()["detail"] == "request_id does not match the current birth request"
    )
    assert not ack_path.exists()
    assert stage_path.read_bytes() == b"stage"


@pytest.mark.asyncio
async def test_post_ack_malformed_id_rejected(tmp_path):
    app, _, ack_path, stage_path = _isolated_router(tmp_path)
    stage_path.write_bytes(b"stage")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post(
            "/diagnostics/birth/ack",
            json={"request_id": "x"},
            headers={"Authorization": "Bearer test-token"},
        )
    assert r.status_code == 422
    assert not ack_path.exists()
    assert stage_path.read_bytes() == b"stage"


@pytest.mark.asyncio
async def test_post_ack_no_request_rejected(tmp_path):
    app, request_path, ack_path, stage_path = _isolated_router(tmp_path)
    stage_path.write_bytes(b"stage")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post(
            "/diagnostics/birth/ack",
            json={"request_id": "a" * 32},
            headers={"Authorization": "Bearer test-token"},
        )
    assert r.status_code == 409
    assert r.json()["detail"] == "no birth awaiting acknowledgement"
    assert not ack_path.exists()
    assert not request_path.exists()
    assert stage_path.read_bytes() == b"stage"


@pytest.mark.asyncio
async def test_post_ack_unauthorized(tmp_path):
    app, request_path, ack_path, stage_path = _isolated_router(tmp_path)
    stage_path.write_bytes(b"stage")
    request_id = "a" * 32
    write_request(
        BirthRequest(
            request_id=request_id,
            requested_at=datetime.now(timezone.utc).isoformat(),
            gestation_started_at=None,
        ),
        path=request_path,
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post(
            "/diagnostics/birth/ack",
            json={"request_id": request_id},
        )
    assert r.status_code != 200
    assert not ack_path.exists()
    assert stage_path.read_bytes() == b"stage"


@pytest.mark.asyncio
async def test_post_ack_idempotent(tmp_path):
    app, request_path, ack_path, _ = _isolated_router(tmp_path)
    request_id = "a" * 32
    write_request(
        BirthRequest(
            request_id=request_id,
            requested_at=datetime.now(timezone.utc).isoformat(),
            gestation_started_at=None,
        ),
        path=request_path,
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r1 = await c.post(
            "/diagnostics/birth/ack",
            json={"request_id": request_id},
            headers={"Authorization": "Bearer test-token"},
        )
        r2 = await c.post(
            "/diagnostics/birth/ack",
            json={"request_id": request_id},
            headers={"Authorization": "Bearer test-token"},
        )
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["pending"] is False
    assert r2.json()["pending"] is False
    ack = read_ack(ack_path)
    assert ack is not None
    assert ack.request_id == request_id
