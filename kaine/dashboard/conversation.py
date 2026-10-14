# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from kaine import legacy_aliases
from kaine.bus import Event
from kaine.dashboard.diagnostics import asset_url, build_diagnostics_context
from kaine.dashboard.health import HealthProber
from kaine.lifecycle.manager import ForkManager

log = logging.getLogger(__name__)


LANGUAGE_EXTERNAL_STREAM = "language.external"
SLEEP_STREAM = "sleep.out"


def _entry_order(entry_id: Any) -> tuple[int, int]:
    if isinstance(entry_id, bytes):
        entry_id = entry_id.decode()
    ms, _, seq = str(entry_id).partition("-")
    return (int(ms), int(seq or 0))


async def read_conversation_history(bus: Any, n: int) -> list[tuple[str, Event]]:
    """The first ``n`` external utterances, across the renamed stream and its old name.

    After the keys rename the language module writes ``language.external``, while
    utterances from before the rename stay in the old stream until the cleanup
    command removes it. Both are read and merged in Redis id order (ids are
    time-ordered across streams); old events are mapped to the new source and type.
    """
    new_entries: list[tuple[str, Event]] = []
    try:
        new_entries = await bus.read(LANGUAGE_EXTERNAL_STREAM, last_id="0", count=n, block_ms=0)
    except Exception:
        # Still try the old stream: a failed read of the new one must not hide
        # the history written before the rename.
        log.exception("conversation history backfill failed")
    old_entries: list[tuple[str, Event]] = []
    old_stream = legacy_aliases.old_stream_name(LANGUAGE_EXTERNAL_STREAM)
    if old_stream:
        try:
            if await bus.client.exists(old_stream):
                raw_old = await bus.read(old_stream, last_id="0", count=n, block_ms=0)
                old_entries = [
                    (
                        entry_id,
                        event.model_copy(
                            update={
                                "source": legacy_aliases.map_module_key(event.source),
                                "type": legacy_aliases.map_stream(event.type),
                            }
                        ),
                    )
                    for entry_id, event in raw_old
                ]
        except Exception:
            log.exception("conversation history read of the old stream failed")
    merged = sorted(new_entries + old_entries, key=lambda item: _entry_order(item[0]))
    return merged[:n]


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

    def update_from_self_model(self, payload: dict[str, Any]) -> None:
        name = payload.get("entity_name") or payload.get("name")
        if isinstance(name, str) and name.strip():
            self.entity_name = name.strip()

    def update_from_sleep(self, event_type: str) -> None:
        if event_type == "sleep.sleep.started":
            self.sleeping = True
        elif event_type == "sleep.sleep.completed":
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
