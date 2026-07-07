# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Nexus router for the live-perception surface.

Two routes under /diagnostics/perception:

  GET  /diagnostics/perception.json   — current runtime + desired state
  POST /diagnostics/perception/toggle — operator-requested on/off

The router never opens the microphone or camera itself. It only mutates
`state/perception/desired.json`; the LiveMicrophone / LiveCamera tasks
poll that file and start/stop their own streams to match.

The privacy boundary (PrivacyFilter at the BusBridge) is unchanged.
Transcription text never reaches the diagnostics SSE.
"""
from __future__ import annotations

import logging
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, field_validator

from kaine.perception_state import (
    DESIRED_PATH,
    LOCI,
    RUNTIME_PATH,
    read_desired,
    read_runtime,
    write_desired_audio,
    write_desired_locus,
    write_desired_video,
)

log = logging.getLogger(__name__)


class PerceptionToggleBody(BaseModel):
    surface: str = Field(..., description="`audio` or `video`")
    active: bool

    @field_validator("surface")
    @classmethod
    def _validate_surface(cls, v: str) -> str:
        if v not in ("audio", "video"):
            raise ValueError("surface must be 'audio' or 'video'")
        return v


class PerceptionLocusBody(BaseModel):
    locus: str = Field(..., description="physical | virtual | off")
    locked: bool | None = Field(None, description="optionally (un)lock the locus")

    @field_validator("locus")
    @classmethod
    def _validate_locus(cls, v: str) -> str:
        if v not in LOCI:
            raise ValueError(f"locus must be one of {LOCI}")
        return v


def _availability() -> dict[str, bool]:
    """Best-effort check that the optional extras are importable. Used
    by the UI to gray out toggles when the dep isn't installed."""
    out = {"audio_available": False, "video_available": False}
    try:
        import sounddevice  # noqa: F401
        import webrtcvad  # noqa: F401
        out["audio_available"] = True
    except ImportError:
        # Optional [audio] extra not installed — leave audio_available False.
        pass
    try:
        import cv2  # noqa: F401
        out["video_available"] = True
    except ImportError:
        # Optional [vision] extra not installed — leave video_available False.
        pass
    return out


def perception_snapshot() -> dict:
    runtime = read_runtime()
    desired = read_desired()
    snap = {
        "audio_live_active": runtime.audio_live_active,
        "video_live_active": runtime.video_live_active,
        "audio_live_desired": desired.audio_live_desired,
        "video_live_desired": desired.video_live_desired,
        "locus": desired.locus,
        "locus_locked": desired.locus_locked,
        "audio_last_started_at": runtime.audio_last_started_at,
        "video_last_started_at": runtime.video_last_started_at,
        "audio_last_stopped_at": runtime.audio_last_stopped_at,
        "video_last_stopped_at": runtime.video_last_stopped_at,
    }
    snap.update(_availability())
    from kaine import perception_preview

    snap["preview_enabled"] = perception_preview.preview_enabled()
    return snap


# The Nexus proxy talks to the cycle's loopback preview server with a tight
# timeout — it is a same-host request that must either answer immediately or be
# treated as "no preview" (404). Never hang the diagnostics UI on it.
_PREVIEW_PROXY_TIMEOUT_S = 1.0


def build_perception_router(
    *,
    runtime_path: Path | None = None,
    desired_path: Path | None = None,
    preview_port: int | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/diagnostics/perception")
    runtime_path = runtime_path or RUNTIME_PATH
    desired_path = desired_path or DESIRED_PATH

    # Resolve the cycle's loopback preview port lazily + once. `preview_port`
    # may be injected (tests / explicit wiring); otherwise it is read from
    # [perception_preview].port in the merged config on first use.
    _resolved_port: dict[str, int] = {}

    def _preview_port() -> int:
        if preview_port is not None:
            return preview_port
        if "port" not in _resolved_port:
            from kaine.perception_preview_server import preview_port as _pp

            _resolved_port["port"] = _pp()
        return _resolved_port["port"]

    async def _proxy_preview(path: str) -> httpx.Response | None:
        """GET `path` from the cycle's loopback preview server. Returns the
        response, or None when the dev flag is off / the cycle (and thus the
        preview server) is not reachable — both of which the caller maps to a
        404 so the PiP stays hidden."""
        from kaine import perception_preview

        if not perception_preview.preview_enabled():
            return None
        url = f"http://127.0.0.1:{_preview_port()}{path}"
        try:
            async with httpx.AsyncClient(
                timeout=_PREVIEW_PROXY_TIMEOUT_S
            ) as client:
                return await client.get(url)
        except (httpx.HTTPError, OSError):
            # Cycle down / preview server not listening → honest "no preview".
            return None

    @router.get("/.json", include_in_schema=False)
    @router.get(".json")
    async def perception_json():
        runtime = read_runtime(runtime_path)
        desired = read_desired(desired_path)
        snap = {
            "audio_live_active": runtime.audio_live_active,
            "video_live_active": runtime.video_live_active,
            "audio_live_desired": desired.audio_live_desired,
            "video_live_desired": desired.video_live_desired,
            "locus": desired.locus,
            "locus_locked": desired.locus_locked,
            "audio_last_started_at": runtime.audio_last_started_at,
            "video_last_started_at": runtime.video_last_started_at,
            "audio_last_stopped_at": runtime.audio_last_stopped_at,
            "video_last_stopped_at": runtime.video_last_stopped_at,
        }
        snap.update(_availability())
        from kaine import perception_preview

        snap["preview_enabled"] = perception_preview.preview_enabled()
        return JSONResponse(snap)

    @router.post("/toggle")
    async def toggle(body: PerceptionToggleBody):
        if body.surface == "audio":
            new_desired = write_desired_audio(body.active, desired_path)
        else:
            new_desired = write_desired_video(body.active, desired_path)
        log.info(
            "perception toggle requested surface=%s active=%s",
            body.surface,
            body.active,
        )
        return {
            "surface": body.surface,
            "audio_live_desired": new_desired.audio_live_desired,
            "video_live_desired": new_desired.video_live_desired,
        }

    # ---- dev-gated perception preview (paper §4.4 explicit override) --------
    # These surface WHAT THE ENTITY CURRENTLY SEES / how loud it hears. The
    # preview holder is populated inside the CYCLE process; Nexus is a SEPARATE
    # process, so these routes PROXY over a 127.0.0.1-only socket to the cycle's
    # loopback preview server (kaine/perception_preview_server.py), which serves
    # the in-RAM slot. They exist only under the operator dev flag
    # KAINE_PERCEPTION_PREVIEW=1 (checked on both sides); when the flag is off or
    # the cycle isn't up they 404 / report an empty meter, and the PiP stays
    # hidden. Nothing is persisted on either side — RAM slot + sockets only.
    @router.get("/preview/video")
    async def preview_video():
        resp = await _proxy_preview("/video")
        if resp is None or resp.status_code != 200:
            # Flag off, cycle down, or no frame captured yet.
            raise HTTPException(404, "no preview frame")
        return Response(
            content=resp.content,
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/preview/audio")
    async def preview_audio():
        # A JSON level for a meter (metadata only — never PCM). Proxied from the
        # cycle's loopback server; `level` is None when the mic is not feeding.
        resp = await _proxy_preview("/audio")
        if resp is None or resp.status_code != 200:
            raise HTTPException(404, "no preview audio")
        return JSONResponse(
            resp.json(),
            headers={"Cache-Control": "no-store"},
        )

    @router.post("/locus")
    async def set_locus(body: PerceptionLocusBody):
        new_desired = write_desired_locus(body.locus, body.locked, desired_path)
        log.info(
            "perception locus set locus=%s locked=%s",
            new_desired.locus,
            new_desired.locus_locked,
        )
        return {
            "locus": new_desired.locus,
            "locus_locked": new_desired.locus_locked,
        }

    return router
