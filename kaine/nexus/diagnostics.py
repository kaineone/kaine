# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from kaine.lifecycle.manager import ForkManager, UnmergedAdaptersError
from kaine.lifecycle.snapshot import is_valid_snapshot_id
from kaine.lifecycle.timing_profile import (
    InvalidForkTimingProfile,
    build_timing_metadata,
    fork_timing_profile,
)
from kaine.nexus.bridge import BusBridge, event_to_sse_payload
from kaine.nexus.health import HealthProber

log = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"


def asset_url(path: str) -> str:
    """Append a cache-busting `?v=<mtime>` to a `/static/...` URL so the browser
    refetches an asset whenever its file changes (no more stale CSS/JS). Falls
    back to the bare path if the file can't be stat'd."""
    rel = path.split("?", 1)[0]
    if rel.startswith("/static/"):
        f = _STATIC_DIR / rel[len("/static/"):]
        try:
            return f"{rel}?v={int(f.stat().st_mtime)}"
        except OSError:
            return rel
    return path


def _templates() -> Jinja2Templates:
    base = Path(__file__).parent / "templates"
    templates = Jinja2Templates(directory=str(base))
    templates.env.globals["asset"] = asset_url
    return templates


class ForkRequestBody(BaseModel):
    parent_id: str
    label: str = ""
    shed: list[str] = []
    # Optional per-fork subjective-time profile (Phase 4). When time_scale is
    # provided (with optional rate overrides) the keys are packed into the
    # existing fork metadata under "timing" and applied at spawn by the runtime.
    # Absent → a behavior-preserving fork that runs at the prevailing scale.
    time_scale: float | None = None
    processing_rate_hz: float | None = None
    experiential_rate_hz: float | None = None
    vision_sample_hz: float | None = None


class MergeRequestBody(BaseModel):
    snapshot_a_id: str
    snapshot_b_id: str
    label: str = ""
    allow_unmerged_adapters: bool = False


class RateControlBody(BaseModel):
    processing_rate_hz: float | None = None
    experiential_rate_hz: float | None = None


# Every per-block key surfaced by HealthProber.snapshot() is extracted here into
# a flat name the template can render. Adding a block to snapshot() without
# adding its key below would silently orphan it (the bug this list was hardened
# against) — the orphan-guard test in tests/test_nexus_observability.py asserts
# this set stays in sync with snapshot().
HEALTH_BLOCK_KEYS: tuple[str, ...] = (
    "spot",
    "entity_care",
    "research",
    "preservation",
    "welfare",
    "admissibility",
    "perception_feed",
    "cycle_pacing",
    "model_server",
    "voice_alignment_window",
    "gpu_preflight",
    "backends",
)


# How often the server pushes a combined metrics+health snapshot over the
# single diagnostics SSE stream (task 2.2). Never faster than the health
# cache TTL — pushing more often than the cache refreshes would not surface
# fresher data, only waste bandwidth (the same "poll interval < cache TTL"
# mistake task 1.3 fixes on the old client-side pollers).
DEFAULT_SNAPSHOT_PUSH_INTERVAL_S = 5.0


async def push_snapshots_periodically(
    bridge: BusBridge,
    *,
    metrics_snapshot: Callable[[], dict[str, Any]],
    health_prober: HealthProber | None,
    interval_s: float | None = None,
) -> None:
    """Background task: server-push a combined metrics+health snapshot over
    the single diagnostics SSE stream every ``interval_s`` seconds.

    This is what retires the client-side ``NexusVitals``/``NexusMetrics``/
    ``NexusSpot`` polling loops (task 2.2, completing the single-stream
    refactor of task 1.1): the browser now RECEIVES a ``nexus.snapshot``
    event instead of fetching ``/diagnostics/metrics.json`` +
    ``/diagnostics/health.json`` on its own timer. The push cadence defaults
    to the health cache TTL (never faster — see
    :data:`DEFAULT_SNAPSHOT_PUSH_INTERVAL_S`), so this causes no MORE real
    probe traffic than the health board already causes.

    Runs until cancelled (the caller owns the task's lifecycle, matching how
    ``BusBridge.start``/``stop`` are managed). A single failed snapshot is
    logged and never kills the loop — the next tick tries again.
    """
    ttl = (
        health_prober.cache_ttl_s
        if health_prober is not None
        else DEFAULT_SNAPSHOT_PUSH_INTERVAL_S
    )
    wait_s = (
        interval_s
        if interval_s is not None
        else max(DEFAULT_SNAPSHOT_PUSH_INTERVAL_S, ttl)
    )
    while True:
        try:
            metrics = metrics_snapshot()
        except Exception:
            log.warning("snapshot pusher: metrics_snapshot raised", exc_info=True)
            metrics = {}
        health: dict[str, Any] | None = None
        if health_prober is not None:
            try:
                health = await health_prober.snapshot()
            except Exception:
                log.warning("snapshot pusher: health_prober raised", exc_info=True)
        try:
            await bridge.publish_synthetic(
                source="nexus",
                type="nexus.snapshot",
                payload={"metrics": metrics, "health": health},
            )
        except Exception:
            log.warning("snapshot pusher: publish_synthetic raised", exc_info=True)
        await asyncio.sleep(wait_s)


async def build_diagnostics_context(
    *,
    fork_manager: ForkManager | None,
    metrics_snapshot: Callable[[], dict[str, Any]],
    adapters_lister: Callable[[], list[dict[str, Any]]] | None = None,
    dev_content_override: bool = False,
    perception_provider: Callable[[], dict[str, Any]] | None = None,
    cycle_control_provider: Callable[[], dict[str, Any]] | None = None,
    health_prober: HealthProber | None = None,
    rate_control_publisher: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    """Build the template context shared by the diagnostics route and the
    unified console at ``/``.

    Every panel degrades gracefully when its provider is absent (no entity
    running), so this is safe to call with all providers ``None``. The
    per-block extraction of the HealthProber snapshot keys lives here (keyed off
    ``HEALTH_BLOCK_KEYS``) so the orphan-guard contract has a single home.
    """
    forks: list[dict[str, Any]] = []
    if fork_manager is not None:
        for snap_id in fork_manager.list_snapshots():
            try:
                snap = fork_manager.load(snap_id)
                forks.append(
                    {
                        "id": snap.id,
                        "parent_id": snap.parent_id,
                        "label": snap.label,
                        "timestamp": snap.timestamp,
                    }
                )
            except Exception:
                continue
    perception = None
    if perception_provider is not None:
        try:
            perception = perception_provider()
        except Exception:
            log.warning("perception_provider raised", exc_info=True)
    cycle_control = None
    if cycle_control_provider is not None:
        try:
            cycle_control = cycle_control_provider()
        except Exception:
            log.warning("cycle_control_provider raised", exc_info=True)
    health = None
    if health_prober is not None:
        try:
            health = await health_prober.snapshot()
        except Exception:
            log.warning("health_prober raised", exc_info=True)
    block_context: dict[str, Any] = {}
    if health is not None:
        for key in HEALTH_BLOCK_KEYS:
            try:
                block_context[key] = health.get(key)
            except Exception:
                block_context[key] = None
    context: dict[str, Any] = {
        "metrics": metrics_snapshot(),
        "forks": forks,
        "adapters": (adapters_lister() if adapters_lister else []),
        "dev_content_override": dev_content_override,
        "perception": perception,
        "cycle_control": cycle_control,
        "health": health,
        "rate_control_enabled": rate_control_publisher is not None,
    }
    # Flatten each extracted health block under its own key so the template can
    # render it directly (e.g. {{ cycle_pacing }}).
    context.update(block_context)
    return context


def build_diagnostics_router(
    bridge: BusBridge,
    *,
    fork_manager: ForkManager | None,
    metrics_snapshot: Callable[[], dict[str, Any]],
    adapters_lister: Callable[[], list[dict[str, Any]]] | None = None,
    dev_content_override: bool = False,
    perception_provider: Callable[[], dict[str, Any]] | None = None,
    cycle_control_provider: Callable[[], dict[str, Any]] | None = None,
    health_prober: HealthProber | None = None,
    rate_control_publisher: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/diagnostics")
    templates = _templates()

    @router.get("/", response_class=HTMLResponse)
    async def diagnostics_page(request: Request):
        context = await build_diagnostics_context(
            fork_manager=fork_manager,
            metrics_snapshot=metrics_snapshot,
            adapters_lister=adapters_lister,
            dev_content_override=dev_content_override,
            perception_provider=perception_provider,
            cycle_control_provider=cycle_control_provider,
            health_prober=health_prober,
            rate_control_publisher=rate_control_publisher,
        )
        return templates.TemplateResponse(request, "diagnostics.html", context)

    @router.get("/health.json")
    async def health_json():
        if health_prober is None:
            return JSONResponse(
                {"dependencies": [], "modules": [], "checked_at": None}
            )
        return JSONResponse(await health_prober.snapshot())

    @router.post("/cycle/rates")
    async def set_cycle_rates(body: RateControlBody):
        if rate_control_publisher is None:
            raise HTTPException(503, "cycle rate control not configured")
        payload: dict[str, Any] = {}
        if body.processing_rate_hz is not None:
            if body.processing_rate_hz <= 0:
                raise HTTPException(422, "processing_rate_hz must be positive")
            payload["processing_rate_hz"] = float(body.processing_rate_hz)
        if body.experiential_rate_hz is not None:
            if body.experiential_rate_hz <= 0:
                raise HTTPException(422, "experiential_rate_hz must be positive")
            payload["experiential_rate_hz"] = float(body.experiential_rate_hz)
        if not payload:
            raise HTTPException(422, "no rate provided")
        await rate_control_publisher(payload)
        return {"published": True, "rates": payload}

    @router.get("/metrics.json")
    async def metrics_json():
        return JSONResponse(metrics_snapshot())

    @router.get("/forks.json")
    async def forks_json():
        if fork_manager is None:
            return JSONResponse({"forks": []})
        out = []
        for snap_id in fork_manager.list_snapshots():
            try:
                snap = fork_manager.load(snap_id)
                entry: dict[str, Any] = {
                    "id": snap.id,
                    "parent_id": snap.parent_id,
                    "label": snap.label,
                    "timestamp": snap.timestamp,
                }
                # Surface the per-fork subjective-time profile read-only so an
                # operator can see which forks are dilated. A malformed timing
                # block must not blank the whole list, so parse defensively.
                try:
                    profile = fork_timing_profile(snap)
                except InvalidForkTimingProfile:
                    profile = None
                if profile is not None:
                    entry["timing"] = profile.to_metadata()
                out.append(entry)
            except Exception:
                continue
        return JSONResponse({"forks": out})

    @router.post("/forks")
    async def create_fork(body: ForkRequestBody):
        if fork_manager is None:
            raise HTTPException(503, "fork manager not configured")
        # The parent id is untrusted request input and is fed to snapshot path
        # resolution. Reject anything but a well-formed fork/merge id BEFORE it can
        # reach load_snapshot (path-traversal defense; see snapshot.is_valid_snapshot_id).
        if not is_valid_snapshot_id(body.parent_id):
            raise HTTPException(422, f"invalid parent_id: {body.parent_id!r}")
        # Pack any provided timing fields into the existing fork metadata under
        # "timing". The typed builder validates eagerly (e.g. time_scale <= 0),
        # so a bad value is a 422 here rather than a silently-stored half-profile.
        try:
            metadata = build_timing_metadata(
                time_scale=body.time_scale,
                processing_rate_hz=body.processing_rate_hz,
                experiential_rate_hz=body.experiential_rate_hz,
                vision_sample_hz=body.vision_sample_hz,
            )
        except InvalidForkTimingProfile as exc:
            raise HTTPException(422, str(exc))
        try:
            snap = fork_manager.fork(
                body.parent_id,
                label=body.label,
                shed=tuple(body.shed),
                metadata=metadata or None,
            )
        except FileNotFoundError:
            raise HTTPException(404, f"parent snapshot {body.parent_id!r} not found")
        out: dict[str, Any] = {
            "id": snap.id,
            "parent_id": snap.parent_id,
            "label": snap.label,
        }
        profile = fork_timing_profile(snap)
        if profile is not None:
            out["timing"] = profile.to_metadata()
        return out

    @router.post("/merges")
    async def create_merge(body: MergeRequestBody):
        if fork_manager is None:
            raise HTTPException(503, "fork manager not configured")
        # Both parent ids are untrusted and reach snapshot path resolution — reject
        # any malformed id before load_snapshot (path-traversal defense).
        for name, snapshot_id in (
            ("snapshot_a_id", body.snapshot_a_id),
            ("snapshot_b_id", body.snapshot_b_id),
        ):
            if not is_valid_snapshot_id(snapshot_id):
                raise HTTPException(422, f"invalid {name}: {snapshot_id!r}")
        try:
            snap = fork_manager.merge(
                body.snapshot_a_id,
                body.snapshot_b_id,
                label=body.label,
                allow_unmerged_adapters=body.allow_unmerged_adapters,
            )
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc))
        except UnmergedAdaptersError as exc:
            # Both parents have trained adapters but no real merger is
            # configured.  Expose the reason so the operator can take action
            # (install [lifecycle.adapter_merge] or pass allow_unmerged_adapters).
            raise HTTPException(409, str(exc))
        return {"id": snap.id, "parent_id": snap.parent_id, "label": snap.label}

    @router.get("/stream")
    async def diagnostics_stream(request: Request):
        client = bridge.add_client("diagnostics")

        async def gen():
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        entry_id, event = await asyncio.wait_for(
                            client.queue.get(), timeout=15.0
                        )
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    payload = event_to_sse_payload(entry_id, event)
                    yield f"data: {json.dumps(payload)}\n\n"
            finally:
                bridge.remove_client(client)

        return StreamingResponse(gen(), media_type="text/event-stream")

    return router
