# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Nexus router for caretaker unattended-start acknowledgement.

Two routes under /diagnostics:

  GET  /diagnostics/caretaker.json  — current start/ack state
  POST /diagnostics/caretaker/ack    — operator acknowledges the start

The cycle writes ``state/cycle/caretaker_start.json``; Nexus writes ONLY the
acknowledgement record. Nothing here ever creates or modifies the start file.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from kaine.cycle.caretaker_state import (
    CaretakerAck,
    is_acknowledged,
    read_ack,
    read_start,
    write_ack,
)
from kaine.nexus.auth import require_operator_token

log = logging.getLogger(__name__)


class AckBody(BaseModel):
    start_id: str = Field(pattern=r"^[0-9a-f]{32}$")


NO_CACHE = {"Cache-Control": "no-store"}


def caretaker_snapshot(*, start_path: Path | None = None, ack_path: Path | None = None) -> dict:
    start = read_start(path=start_path)
    ack = read_ack(path=ack_path)
    if start is None:
        return {
            "pending": False,
            "start_id": None,
            "started_at": None,
            "acknowledged_at": None,
        }
    if is_acknowledged(start, ack):
        return {
            "pending": False,
            "start_id": start.start_id,
            "started_at": start.started_at,
            "acknowledged_at": ack.acknowledged_at,
        }
    return {
        "pending": True,
        "start_id": start.start_id,
        "started_at": start.started_at,
        "acknowledged_at": None,
    }


def build_caretaker_router(*, start_path: Path | None = None, ack_path: Path | None = None) -> APIRouter:
    router = APIRouter(prefix="/diagnostics")

    @router.get("/caretaker.json", include_in_schema=False)
    @router.get("/caretaker")
    async def caretaker_json():
        return JSONResponse(caretaker_snapshot(start_path=start_path, ack_path=ack_path), headers=NO_CACHE)

    @router.post("/caretaker/ack", dependencies=[Depends(require_operator_token)])
    async def caretaker_ack(body: AckBody):
        start = read_start(path=start_path)
        if start is None:
            raise HTTPException(status_code=409, detail="no unattended start to acknowledge")
        if body.start_id != start.start_id:
            raise HTTPException(status_code=409, detail="start_id does not match the current unattended start")

        ack = CaretakerAck(
            start_id=start.start_id,
            acknowledged_at=datetime.now(timezone.utc).isoformat(),
        )
        write_ack(ack, path=ack_path)
        log.info("caretaker acknowledged unattended start")
        return JSONResponse(caretaker_snapshot(start_path=start_path, ack_path=ack_path), headers=NO_CACHE)

    return router
