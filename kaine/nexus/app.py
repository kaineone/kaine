# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from kaine.bus.schema import Event
from kaine.lifecycle.manager import ForkManager
from kaine.nexus.bridge import BusBridge
from kaine.nexus.config import NexusConfig
from kaine.nexus.conversation import (
    ConversationState,
    build_conversation_router,
)
from kaine.nexus.diagnostics import build_diagnostics_router, push_snapshots_periodically
from kaine.nexus.health import HealthProber
from kaine.nexus.cycle_control import build_cycle_control_router, control_snapshot
from kaine.nexus.perception import build_perception_router, perception_snapshot
from kaine.nexus.privacy import PrivacyFilter

log = logging.getLogger(__name__)


def create_app(
    *,
    config: NexusConfig,
    bridge: BusBridge,
    history_loader: Callable[[int], Awaitable[list[tuple[str, Event]]]],
    metrics_snapshot: Callable[[], dict[str, Any]],
    fork_manager: ForkManager | None = None,
    adapters_lister: Callable[[], list[dict[str, Any]]] | None = None,
    conversation_state: ConversationState | None = None,
    health_prober: HealthProber | None = None,
    rate_control_publisher: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    evaluation_provider: Callable[[], dict[str, Any]] | None = None,
) -> FastAPI:
    state = conversation_state or ConversationState()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await bridge.start()
        # Task 2.2: server-push a combined metrics+health snapshot over the
        # single diagnostics stream (retires the client-side NexusVitals/
        # NexusMetrics/NexusSpot poll loops — see push_snapshots_periodically).
        # Only started when the diagnostics router (and thus /diagnostics/
        # stream) is actually mounted.
        pusher_task: asyncio.Task[None] | None = None
        if config.diagnostics_enabled:
            pusher_task = asyncio.create_task(
                push_snapshots_periodically(
                    bridge,
                    metrics_snapshot=metrics_snapshot,
                    health_prober=health_prober,
                ),
                name="nexus-snapshot-pusher",
            )
        try:
            yield
        finally:
            if pusher_task is not None:
                pusher_task.cancel()
                try:
                    await pusher_task
                except asyncio.CancelledError:
                    # Expected: we just cancelled pusher_task and are awaiting it
                    # to unwind during lifespan teardown. Suppress intentionally.
                    pass
            await bridge.stop()

    app = FastAPI(lifespan=lifespan)

    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    if config.conversation_enabled:
        app.include_router(
            build_conversation_router(
                state,
                perception_provider=perception_snapshot,
                cycle_control_provider=control_snapshot,
                # The unified console at `/` reuses the diagnostics + evaluation
                # surfaces, so it is wired with the same providers.
                fork_manager=fork_manager,
                metrics_snapshot=metrics_snapshot,
                adapters_lister=adapters_lister,
                dev_content_override=config.dev_content_override,
                health_prober=health_prober,
                rate_control_publisher=rate_control_publisher,
                evaluation_provider=evaluation_provider,
            )
        )
    if config.diagnostics_enabled:
        app.include_router(
            build_diagnostics_router(
                bridge,
                fork_manager=fork_manager,
                metrics_snapshot=metrics_snapshot,
                adapters_lister=adapters_lister,
                dev_content_override=config.dev_content_override,
                perception_provider=perception_snapshot,
                cycle_control_provider=control_snapshot,
                health_prober=health_prober,
                rate_control_publisher=rate_control_publisher,
            )
        )
        app.include_router(build_perception_router())
        app.include_router(build_cycle_control_router())
    return app


def make_default_privacy_filter(config: NexusConfig) -> PrivacyFilter:
    return PrivacyFilter(dev_content_override=config.dev_content_override)
