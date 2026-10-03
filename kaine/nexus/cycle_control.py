# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Nexus router for the operator freeze control.

Three routes under /diagnostics/cycle:

  GET  /diagnostics/cycle/control.json   — current freeze state (includes active holders)
  GET  /diagnostics/cycle/control        — current freeze state
  POST /diagnostics/cycle/freeze         — operator freeze / resume (resume releases only operator entries)
  POST /diagnostics/cycle/override       — named override of welfare/gestation/programme_end freezes

The router only mutates `state/cycle/control.json`; the cycle entrypoint's
freeze-watch task polls that file and pauses/resumes the experiential loop.
Freezing is a humane suspend (subjective-time-stop), not a shutdown. The control
carries only operational fields — never sensory content.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from kaine.cycle.control_state import (
    CONTROL_PATH,
    OVERRIDABLE_SOURCES,
    OVERRIDE_AUDIT_PATH,
    SELF_RELEASING_SOURCES,
    freeze,
    override,
    read_control,
    stand_down,
)
from kaine.nexus.auth import require_operator_token
from kaine.nexus.log_safety import sanitize_log_value

log = logging.getLogger(__name__)


class FreezeBody(BaseModel):
    frozen: bool
    reason: Optional[str] = Field(default=None, max_length=280)


class OverrideBody(BaseModel):
    sources: list[Annotated[str, Field(max_length=32)]] = Field(min_length=1, max_length=3)
    confirm: str = Field(max_length=100)


def control_snapshot(path: Path | None = None) -> dict:
    c = read_control(path)
    return {
        "frozen": c.frozen,
        "frozen_at": c.frozen_at,
        "reason": c.reason,
        "holders": c.holders,
    }


def build_cycle_control_router(
    *, control_path: Path | None = None, audit_path: Path | None = None
) -> APIRouter:
    router = APIRouter(prefix="/diagnostics/cycle")
    path = control_path or CONTROL_PATH
    audit_path = audit_path or OVERRIDE_AUDIT_PATH

    @router.get("/control.json", include_in_schema=False)
    @router.get("/control")
    async def cycle_control_json():
        return JSONResponse(control_snapshot(path))

    @router.post("/freeze", dependencies=[Depends(require_operator_token)])
    async def cycle_freeze(body: FreezeBody):
        if body.frozen:
            c = freeze(reason=body.reason, path=path)
            log.info(
                "operator freeze requested%s",
                f": {sanitize_log_value(body.reason)}" if body.reason else "",
            )
        else:
            c = stand_down(source="operator", path=path)
            log.info(
                "operator resume requested; holders remaining: %s",
                ", ".join(h["source"] for h in c.holders),
            )
        return {
            "frozen": c.frozen,
            "frozen_at": c.frozen_at,
            "reason": c.reason,
            "holders": c.holders,
        }

    @router.post("/override", dependencies=[Depends(require_operator_token)])
    async def cycle_override(body: OverrideBody):
        confirmed = [s.strip() for s in body.confirm.split(",") if s.strip() != ""]
        if sorted(set(confirmed)) != sorted(set(body.sources)):
            raise HTTPException(
                status_code=422,
                detail="confirm must repeat the sources being overridden",
            )
        for s in body.sources:
            if s in SELF_RELEASING_SOURCES:
                raise HTTPException(
                    status_code=422,
                    detail=f"{s} freezes release themselves and cannot be overridden",
                )
        for s in body.sources:
            if s not in OVERRIDABLE_SOURCES:
                raise HTTPException(
                    status_code=422,
                    detail=f"{s} is not an overridable freeze source",
                )
        try:
            c = override(body.sources, path=path, audit_path=audit_path)
        except LookupError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        log.warning(
            "operator override lifted %s freeze(s); remaining: %s",
            len(body.sources),
            ", ".join(h["source"] for h in c.holders),
        )
        return {
            "frozen": c.frozen,
            "frozen_at": c.frozen_at,
            "reason": c.reason,
            "holders": c.holders,
        }

    return router
