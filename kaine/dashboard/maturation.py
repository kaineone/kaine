# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The dashboard router for operator maturation acknowledgement.

Two routes under /diagnostics:

  GET  /diagnostics/maturation.json  — current maturation request/ack state plus developmental progress.
  POST /diagnostics/maturation/ack   — operator acknowledges the maturation

The maturation gate writes ``state/lifecycle/maturation_request.json``; the dashboard writes
ONLY the acknowledgement record. Nothing here ever creates or modifies the
request file or the stage file.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from kaine import legacy_names
from kaine.dashboard.auth import require_operator_token
from kaine.lifecycle.maturation_ack import (
    MaturationAck,
    is_acknowledged,
    read_ack,
    read_request,
    write_ack,
)
from kaine.storage import resolve

log = logging.getLogger(__name__)

# The routes' name before the rename, kept as hidden aliases for a page loaded
# before the upgrade. Taken from the table, so a rename run cannot fold the alias
# into the route it stands for.
_OLD_ROUTE = next(entry["old"] for entry in legacy_names.STORED_TAGS if entry["new"] == "maturation")


class AckBody(BaseModel):
    request_id: str = Field(pattern=r"^[0-9a-f]{32}$")


NO_CACHE = {"Cache-Control": "no-store"}

RUNTIME_PATH = Path("state/cycle/runtime.json")

_DEVELOPMENT_KEYS = {
    "stage",
    "development_started_at",
    "born_at",
    "lived_seconds",
    "sleep_count",
    "consolidation_passes",
    "readiness",
    "readout",
    "decision",
    "awaiting_ack",
}


def read_development(runtime_path: Path | None = None) -> dict | None:
    if runtime_path is None:
        runtime_path = RUNTIME_PATH
    runtime_path = resolve(runtime_path)
    try:
        raw = json.loads(runtime_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    block = raw.get("developmental_stage") if isinstance(raw, dict) else None
    if not isinstance(block, dict):
        return None
    return {k: block[k] for k in block if k in _DEVELOPMENT_KEYS}


def maturation_snapshot(
    *,
    request_path: Path | None = None,
    ack_path: Path | None = None,
    runtime_path: Path | None = None,
) -> dict:
    request = read_request(path=request_path)
    ack = read_ack(path=ack_path)
    if request is None:
        snapshot = {
            "pending": False,
            "request_id": None,
            "requested_at": None,
            "acknowledged_at": None,
        }
    elif is_acknowledged(request, ack):
        snapshot = {
            "pending": False,
            "request_id": request.request_id,
            "requested_at": request.requested_at,
            "acknowledged_at": ack.acknowledged_at,
        }
    else:
        snapshot = {
            "pending": True,
            "request_id": request.request_id,
            "requested_at": request.requested_at,
            "acknowledged_at": None,
        }
    snapshot["development"] = read_development(runtime_path=runtime_path)
    return snapshot


def build_maturation_router(
    *,
    request_path: Path | None = None,
    ack_path: Path | None = None,
    runtime_path: Path | None = RUNTIME_PATH,
) -> APIRouter:
    router = APIRouter(prefix="/diagnostics")

    @router.get("/maturation.json", include_in_schema=False)
    @router.get("/maturation")
    @router.get(f"/{_OLD_ROUTE}.json", include_in_schema=False)
    @router.get(f"/{_OLD_ROUTE}", include_in_schema=False)
    async def maturation_json():
        return JSONResponse(
            maturation_snapshot(
                request_path=request_path,
                ack_path=ack_path,
                runtime_path=runtime_path,
            ),
            headers=NO_CACHE,
        )

    @router.post("/maturation/ack", dependencies=[Depends(require_operator_token)])
    @router.post(
        f"/{_OLD_ROUTE}/ack", dependencies=[Depends(require_operator_token)], include_in_schema=False
    )
    async def maturation_ack(body: AckBody):
        request = read_request(path=request_path)
        if request is None:
            raise HTTPException(status_code=409, detail="no maturation awaiting acknowledgement")
        if body.request_id != request.request_id:
            raise HTTPException(
                status_code=409,
                detail="request_id does not match the current maturation request",
            )

        ack = MaturationAck(
            request_id=request.request_id,
            acknowledged_at=datetime.now(timezone.utc).isoformat(),
        )
        write_ack(ack, path=ack_path)
        log.info("operator acknowledged maturation")
        return JSONResponse(
            maturation_snapshot(
                request_path=request_path,
                ack_path=ack_path,
                runtime_path=runtime_path,
            ),
            headers=NO_CACHE,
        )

    return router
