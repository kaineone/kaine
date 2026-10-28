# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The dashboard router for operator maturation acknowledgement.

Two routes under /diagnostics:

  GET  /diagnostics/maturation.json  - current maturation request/ack state plus developmental progress and hearing stage (with its dwell, read from state/lifecycle/hearing_stage.json).
  POST /diagnostics/maturation/ack   — operator acknowledges the maturation

The maturation gate writes ``state/lifecycle/maturation_request.json``; the dashboard writes
ONLY the acknowledgement record. Nothing here ever creates or modifies the
request file or the stage file.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from kaine import legacy_names
from kaine.dashboard.auth import require_operator_token
from kaine.lifecycle import stage as lifecycle_stage
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
    "sensory_schedule",
    "sleep_count",
    "consolidation_passes",
    "readiness",
    "readout",
    "decision",
    "awaiting_ack",
    "world",
    "conditions",
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


def _read_hearing_dwell(stage: int, hearing_stage_path: Path | None) -> float | None:
    """Awake seconds in ``stage``, from the stage's single owner file, or None.

    The owner file holds the stage and its dwell. A dwell is returned only when the
    file names the same stage as the runtime reading, so a step between the two
    writes never shows the old stage's dwell against the new stage.
    """
    if hearing_stage_path is None:
        hearing_stage_path = Path(lifecycle_stage.STAGE_PATH).parent / "hearing_stage.json"
    try:
        raw = json.loads(resolve(hearing_stage_path).read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(raw, dict) or raw.get("stage") != stage:
        return None
    dwell = raw.get("dwell_seconds")
    if isinstance(dwell, bool) or not isinstance(dwell, (int, float)):
        return None
    if not math.isfinite(dwell) or dwell < 0:
        return None
    return dwell


def read_hearing_stage(
    runtime_path: Path | None = None, hearing_stage_path: Path | None = None
) -> dict | None:
    if runtime_path is None:
        runtime_path = RUNTIME_PATH
    runtime_path = resolve(runtime_path)
    try:
        raw = json.loads(runtime_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    block = raw.get("hearing_stage")
    if not isinstance(block, dict):
        return None

    def _finite(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if not math.isfinite(value):
            return None
        return value

    stage = block.get("stage")
    if isinstance(stage, bool) or not isinstance(stage, int) or stage < 0 or stage > 4:
        return None

    previous_stage = block.get("previous_stage")
    if (
        isinstance(previous_stage, bool)
        or not isinstance(previous_stage, int)
        or previous_stage < 0
        or previous_stage > 4
    ):
        previous_stage = None

    return {
        "stage": stage,
        "previous_stage": previous_stage,
        "low_hz": _finite(block.get("low_hz")),
        "high_hz": _finite(block.get("high_hz")),
        "awake_seconds": _finite(block.get("awake_seconds")),
        "dwell_seconds": _read_hearing_dwell(stage, hearing_stage_path),
        "min_dwell_seconds": _finite(block.get("min_dwell_seconds")),
        "max_dwell_seconds": _finite(block.get("max_dwell_seconds")),
    }


def maturation_snapshot(
    *,
    request_path: Path | None = None,
    ack_path: Path | None = None,
    runtime_path: Path | None = None,
    hearing_stage_path: Path | None = None,
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
    snapshot["hearing"] = read_hearing_stage(
        runtime_path=runtime_path, hearing_stage_path=hearing_stage_path
    )
    return snapshot


def build_maturation_router(
    *,
    request_path: Path | None = None,
    ack_path: Path | None = None,
    runtime_path: Path | None = RUNTIME_PATH,
    hearing_stage_path: Path | None = None,
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
                hearing_stage_path=hearing_stage_path,
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
                hearing_stage_path=hearing_stage_path,
            ),
            headers=NO_CACHE,
        )

    return router
