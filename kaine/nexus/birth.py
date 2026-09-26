# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Nexus router for operator birth acknowledgement.

Two routes under /diagnostics:

  GET  /diagnostics/birth.json  — current birth request/ack state
  POST /diagnostics/birth/ack   — operator acknowledges the birth

The maturation gate writes ``state/lifecycle/birth_request.json``; Nexus writes
ONLY the acknowledgement record. Nothing here ever creates or modifies the
request file or the stage file.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from kaine.lifecycle.birth_ack import (
    BirthAck,
    is_acknowledged,
    read_ack,
    read_request,
    write_ack,
)
from kaine.nexus.auth import require_operator_token

log = logging.getLogger(__name__)


class AckBody(BaseModel):
    request_id: str = Field(pattern=r"^[0-9a-f]{32}$")


NO_CACHE = {"Cache-Control": "no-store"}


def birth_snapshot(*, request_path: Path | None = None, ack_path: Path | None = None) -> dict:
    request = read_request(path=request_path)
    ack = read_ack(path=ack_path)
    if request is None:
        return {
            "pending": False,
            "request_id": None,
            "requested_at": None,
            "acknowledged_at": None,
        }
    if is_acknowledged(request, ack):
        return {
            "pending": False,
            "request_id": request.request_id,
            "requested_at": request.requested_at,
            "acknowledged_at": ack.acknowledged_at,
        }
    return {
        "pending": True,
        "request_id": request.request_id,
        "requested_at": request.requested_at,
        "acknowledged_at": None,
    }


def build_birth_router(*, request_path: Path | None = None, ack_path: Path | None = None) -> APIRouter:
    router = APIRouter(prefix="/diagnostics")

    @router.get("/birth.json", include_in_schema=False)
    @router.get("/birth")
    async def birth_json():
        return JSONResponse(birth_snapshot(request_path=request_path, ack_path=ack_path), headers=NO_CACHE)

    @router.post("/birth/ack", dependencies=[Depends(require_operator_token)])
    async def birth_ack(body: AckBody):
        request = read_request(path=request_path)
        if request is None:
            raise HTTPException(status_code=409, detail="no birth awaiting acknowledgement")
        if body.request_id != request.request_id:
            raise HTTPException(status_code=409, detail="request_id does not match the current birth request")

        ack = BirthAck(
            request_id=request.request_id,
            acknowledged_at=datetime.now(timezone.utc).isoformat(),
        )
        write_ack(ack, path=ack_path)
        log.info("operator acknowledged birth")
        return JSONResponse(birth_snapshot(request_path=request_path, ack_path=ack_path), headers=NO_CACHE)

    return router
