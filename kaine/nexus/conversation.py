# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from kaine.lifecycle.manager import ForkManager
from kaine.nexus.diagnostics import asset_url, build_diagnostics_context
from kaine.nexus.health import HealthProber

log = logging.getLogger(__name__)


LINGUA_EXTERNAL_STREAM = "lingua.external"
HYPNOS_STREAM = "hypnos.out"


def _templates() -> Jinja2Templates:
    base = Path(__file__).parent / "templates"
    templates = Jinja2Templates(directory=str(base))
    templates.env.globals["asset"] = asset_url
    return templates


class ConversationState:
    """Holds entity-name + sleep-status mutable state for the conversation
    surface. Updated from the bridge via lightweight observers."""

    def __init__(self) -> None:
        self.entity_name: str = "KAINE"
        self.sleeping: bool = False

    def update_from_eidolon(self, payload: dict[str, Any]) -> None:
        name = payload.get("entity_name") or payload.get("name")
        if isinstance(name, str) and name.strip():
            self.entity_name = name.strip()

    def update_from_hypnos(self, event_type: str) -> None:
        if event_type == "hypnos.sleep.started":
            self.sleeping = True
        elif event_type == "hypnos.sleep.completed":
            self.sleeping = False


def build_conversation_router(
    state: ConversationState,
    *,
    perception_provider: Callable[[], dict[str, Any]] | None = None,
    cycle_control_provider: Callable[[], dict[str, Any]] | None = None,
    # The unified console at ``/`` renders the diagnostics and evaluation
    # surfaces. These providers are the same ones the diagnostics route is
    # wired with; all are optional so the page still renders (every panel
    # empty) when no entity is running.
    fork_manager: ForkManager | None = None,
    metrics_snapshot: Callable[[], dict[str, Any]] | None = None,
    adapters_lister: Callable[[], list[dict[str, Any]]] | None = None,
    dev_content_override: bool = False,
    health_prober: HealthProber | None = None,
    rate_control_publisher: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    evaluation_provider: Callable[[], dict[str, Any]] | None = None,
) -> APIRouter:
    router = APIRouter()
    templates = _templates()

    @router.get("/", response_class=HTMLResponse)
    async def console_page(request: Request):
        # The full diagnostics context (metrics, forks, adapters, health blocks,
        # perception, cycle_control, …) — shared verbatim with /diagnostics/ so
        # the same partials render here. Falls back to a not-running snapshot.
        diag = await build_diagnostics_context(
            fork_manager=fork_manager,
            metrics_snapshot=metrics_snapshot or (lambda: {"cycle_status": "not running"}),
            adapters_lister=adapters_lister,
            dev_content_override=dev_content_override,
            perception_provider=perception_provider,
            cycle_control_provider=cycle_control_provider,
            health_prober=health_prober,
            rate_control_publisher=rate_control_publisher,
        )
        evaluation: dict[str, Any] | None = None
        if evaluation_provider is not None:
            try:
                evaluation = evaluation_provider()
            except Exception:
                log.warning("evaluation_provider raised", exc_info=True)
        context: dict[str, Any] = {
            "entity_name": state.entity_name,
            "sleeping": state.sleeping,
            "evaluation": evaluation,
        }
        # The diagnostics context owns `perception` and `cycle_control`; let it
        # win so the banner and the diagnostics panels agree.
        context.update(diag)
        return templates.TemplateResponse(request, "console.html", context)

    return router
