# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Nexus router for the operator freeze control.

Two routes under /diagnostics/cycle:

  GET  /diagnostics/cycle/control.json   — current freeze state
  POST /diagnostics/cycle/freeze         — operator freeze / resume

The router only mutates `state/cycle/control.json`; the cycle entrypoint's
freeze-watch task polls that file and pauses/resumes the experiential loop.
Freezing is a humane suspend (subjective-time-stop), not a shutdown. The control
carries only operational fields — never sensory content.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from kaine.cycle.control_state import CONTROL_PATH, freeze, read_control, unfreeze

log = logging.getLogger(__name__)


class FreezeBody(BaseModel):
    frozen: bool
    reason: Optional[str] = Field(default=None, max_length=280)


def control_snapshot(path: Path | None = None) -> dict:
    c = read_control(path)
    return {"frozen": c.frozen, "frozen_at": c.frozen_at, "reason": c.reason}


def build_cycle_control_router(*, control_path: Path | None = None) -> APIRouter:
    router = APIRouter(prefix="/diagnostics/cycle")
    path = control_path or CONTROL_PATH

    @router.get("/control.json", include_in_schema=False)
    @router.get("/control")
    async def cycle_control_json():
        return JSONResponse(control_snapshot(path))

    @router.post("/freeze")
    async def cycle_freeze(body: FreezeBody):
        if body.frozen:
            c = freeze(reason=body.reason, path=path)
            log.info(
                "operator freeze requested%s",
                f": {body.reason}" if body.reason else "",
            )
        else:
            c = unfreeze(path=path)
            log.info("operator resume requested")
        return {"frozen": c.frozen, "frozen_at": c.frozen_at, "reason": c.reason}

    return router
