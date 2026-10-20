# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import json
import logging
import math
import re
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from kaine import legacy_aliases
from kaine.bus import Event
from kaine.dashboard.diagnostics import asset_url, build_diagnostics_context
from kaine.dashboard.health import HealthProber
from kaine.lifecycle.manager import ForkManager

log = logging.getLogger(__name__)


LANGUAGE_EXTERNAL_STREAM = "language.external"
SLEEP_STREAM = "sleep.out"

_LABEL_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


def _label(value: Any) -> str | None:
    if isinstance(value, str) and _LABEL_RE.fullmatch(value):
        return value
    return None


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    return None


def _entry_order(entry_id: Any) -> tuple[int, int]:
    if isinstance(entry_id, bytes):
        entry_id = entry_id.decode()
    ms, _, seq = str(entry_id).partition("-")
    return (int(ms), int(seq or 0))


def read_entity_name(self_model_path: Path, identity_path: Path) -> str | None:
    """Return a non-empty name from the self-model file or the identity file."""
    if self_model_path.is_file():
        try:
            from kaine.modules.self_model.document import load

            doc = load(self_model_path)
            name = getattr(doc, "name", None)
            if isinstance(name, str) and name.strip():
                return name.strip()
        except Exception:
            log.debug("failed to read self-model name", exc_info=True)

    if identity_path.is_file():
        try:
            data = json.loads(identity_path.read_text())
            if isinstance(data, dict):
                name = data.get("name")
                if isinstance(name, str) and name.strip():
                    return name.strip()
        except Exception:
            log.debug("failed to read identity name", exc_info=True)

    return None


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
    """Holds entity-name, sleep-status and sleep/rest diagnostics state.
    Updated from the bridge via lightweight observers."""

    def __init__(self) -> None:
        self.entity_name: str = "KAINE"
        self.sleeping: bool = False
        self.sleep: dict[str, Any] | None = None
        self.rest_request: dict[str, Any] | None = None
        self._sleep_start_seen: bool = False
        self._sleep_start_trigger: str | None = None

    def observe(self, event: Event) -> None:
        """Update name, sleep state, or sleep/rest diagnostics from an event."""
        if event.type == "self_model.document":
            if isinstance(event.payload, dict):
                self.update_from_self_model({"name": event.payload.get("name")})
        elif event.type == "sleep.sleep.started":
            self.update_from_sleep(event.type)
            self._on_sleep_started(event)
        elif event.type == "sleep.sleep.completed":
            self.update_from_sleep(event.type)
            self._on_sleep_completed(event)
        elif event.type == "affect.rest_request":
            self._on_rest_request(event)

    def _on_sleep_started(self, event: Event) -> None:
        payload = event.payload if isinstance(event.payload, dict) else {}
        trigger = _label(payload.get("trigger"))
        self._sleep_start_seen = True
        self._sleep_start_trigger = trigger
        self.sleep = {
            "asleep": True,
            "trigger": trigger,
            "started_at": _finite(payload.get("started_at")),
            "duration_s": None,
            "rest_seconds": None,
            "aborted": False,
            "completed_at": None,
        }

    def _on_sleep_completed(self, event: Event) -> None:
        payload = event.payload if isinstance(event.payload, dict) else {}
        trigger: str | None = _label(payload.get("trigger"))
        if trigger is None and self._sleep_start_seen and self._sleep_start_trigger is not None:
            trigger = self._sleep_start_trigger
        elif trigger is None and self._sleep_start_seen:
            # The sleep module sets fatigue_triggered at the first fatigue sleep and never
            # clears it, so True cannot tell fatigue from the backstop for later sleeps.
            if payload.get("fatigue_triggered") is True:
                trigger = "fatigue_or_backstop"
            else:
                trigger = "backstop"

        started_at = self.sleep.get("started_at") if isinstance(self.sleep, dict) else None
        total_ms = _finite(payload.get("total_elapsed_ms"))
        duration_s = total_ms / 1000.0 if total_ms is not None else None

        self.sleep = {
            "asleep": False,
            "trigger": trigger,
            "started_at": started_at,
            "duration_s": duration_s,
            "rest_seconds": _finite(payload.get("rest_seconds")),
            "aborted": payload.get("aborted") is True,
            "completed_at": event.timestamp.isoformat(),
        }
        self._sleep_start_seen = False
        self._sleep_start_trigger = None

    def _on_rest_request(self, event: Event) -> None:
        payload = event.payload if isinstance(event.payload, dict) else {}
        self.rest_request = {
            "reason": _label(payload.get("reason")),
            "drive": _label(payload.get("drive")),
            "stall_s": _finite(payload.get("stall_s")),
            "at": event.timestamp.isoformat(),
        }

    def sleep_snapshot(self) -> dict[str, Any]:
        return {
            "sleeping": self.sleeping,
            "sleep": dict(self.sleep) if self.sleep else None,
            "rest_request": dict(self.rest_request) if self.rest_request else None,
        }

    async def backfill(self, bus: Any, *, scan: int = 2000) -> None:
        """Read recent self-model, sleep and affect events and apply the newest matches."""
        try:
            entries = await bus.recent("self_model.out", count=scan)
        except Exception:
            log.debug("conversation backfill failed for self_model.out", exc_info=True)
        else:
            for entry_id, event in entries:
                if event.type == "self_model.document":
                    self.observe(event)
                    break

        try:
            entries = await bus.recent("sleep.out", count=scan)
        except Exception:
            log.debug("conversation backfill failed for sleep.out", exc_info=True)
        else:
            newest_idx: int | None = None
            for i, (entry_id, event) in enumerate(entries):
                if event.type in ("sleep.sleep.started", "sleep.sleep.completed"):
                    newest_idx = i
                    break

            if newest_idx is not None:
                newest_event = entries[newest_idx][1]
                if newest_event.type == "sleep.sleep.started":
                    self.observe(newest_event)
                else:
                    start_idx: int | None = None
                    for j in range(newest_idx + 1, len(entries)):
                        if entries[j][1].type == "sleep.sleep.started":
                            start_idx = j
                            break
                    if start_idx is not None:
                        self.observe(entries[start_idx][1])
                    self.observe(newest_event)

        try:
            entries = await bus.recent("affect.out", count=scan)
        except Exception:
            log.debug("conversation backfill failed for affect.out", exc_info=True)
        else:
            for entry_id, event in entries:
                if event.type == "affect.rest_request":
                    self.observe(event)
                    break

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


def build_sleep_router(state: ConversationState) -> APIRouter:
    router = APIRouter()

    @router.get("/diagnostics/sleep.json")
    async def sleep_diagnostics():
        return JSONResponse(
            state.sleep_snapshot(),
            headers={"Cache-Control": "no-store"},
        )

    return router
