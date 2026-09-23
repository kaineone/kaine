# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles

from kaine.bus.schema import Event
from kaine.lifecycle.manager import ForkManager
from kaine.nexus.auth import (
    LoginRateLimiter,
    NexusAuthError,
    SessionStore,
    auth_error_handler,
    build_auth_router,
    require_operator_token,
)
from kaine.nexus.bridge import BusBridge
from kaine.nexus.config import NexusConfig
from kaine.nexus.conversation import (
    ConversationState,
    build_conversation_router,
)
from kaine.nexus.csrf import NexusCSRFMiddleware
from kaine.nexus.cycle_control import build_cycle_control_router, control_snapshot
from kaine.nexus.diagnostics import (
    build_diagnostics_router,
    build_health_router,
    push_snapshots_periodically,
)
from kaine.nexus.health import HealthProber
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
    app.state.config = config
    app.state.sessions = SessionStore(
        idle_seconds=config.session_idle_minutes * 60,
        max_age_seconds=getattr(config, "session_max_hours", 24) * 3600,
    )
    app.state.login_limiter = LoginRateLimiter(
        max_failures=config.login_max_failures,
        window_s=config.login_failure_window_s,
    )
    app.add_exception_handler(NexusAuthError, auth_error_handler)

    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # CSRF/Origin protection rejects cross-origin or rebinding requests with
    # 403 before they reach route handlers.
    app.add_middleware(NexusCSRFMiddleware, config=config)

    # Auth surface: login/logout and the login form. No auth dependencies.
    app.include_router(build_auth_router(config))

    # Auth dependency: required for state-changing endpoints and privileged
    # read surfaces when conversation or dev content override is enabled.
    privileged_read = config.conversation_enabled or config.dev_content_override
    state_change_dep = [Depends(require_operator_token)]
    read_dep = [Depends(require_operator_token)] if privileged_read else []
    app.state.read_dependencies = read_dep

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
            ),
            dependencies=read_dep,
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
            ),
            dependencies=read_dep,
        )
        # Health endpoint is always unauthenticated so container probes keep
        # working regardless of the privileged-read gate.
        app.include_router(build_health_router(health_prober))
        app.include_router(build_perception_router(), dependencies=state_change_dep)
        app.include_router(build_cycle_control_router(), dependencies=state_change_dep)
    return app


def make_default_privacy_filter(config: NexusConfig) -> PrivacyFilter:
    return PrivacyFilter(dev_content_override=config.dev_content_override)
