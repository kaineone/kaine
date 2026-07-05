# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable, ClassVar, Optional

from kaine.bus.client import AsyncBus
from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.faithful import FaithfulRenderer
from kaine.modules.base import BaseModule
from kaine.modules.lingua.client import (
    ChatClient,
    ChatRequest,
    ChatResponse,
    OpenAIChatClient,
)
from kaine.modules.lingua.context import ContextAssembler
from kaine.modules.lingua.intent_log import IntentExpressionLog
from kaine.workspace.volition import SPEAK, THINK, VOLITION_STREAM

log = logging.getLogger(__name__)

EXTERNAL_STREAM: str = "lingua.external"
INTERNAL_STREAM: str = "lingua.internal"


class Lingua(BaseModule):
    """Language organ — the LLM speaks *from* the conscious workspace, not from
    the bare triggering text.

    Every generation is conditioned by a `ContextAssembler` that builds the
    `(system, prompt)` pair from a first-person persona (seeded from the Eidolon
    self-model) + a rendering of the current conscious coalition + the triggering
    input — the `persona ∪ working-memory ∪ input` shape from CoALA / Generative
    Agents / GWA. Lingua caches the latest broadcast it observed via a passive
    `_snapshot_cache_loop` (it stays intent-driven and never reflexively speaks;
    `on_workspace` remains the BaseModule no-op). External-speech events also
    carry `user_input` so the A/B divergence observer can measure how much the
    cognitive scaffolding moves the output versus a bare-LLM baseline.

    Lingua's bus output goes to two distinct streams. `speak` writes the
    user-facing channel that Chatterbox subscribes to. `think` writes the
    internal-monologue channel that Mnemos consumes and Eidolon counts but
    Chatterbox NEVER reads.

    `_produce()` writes directly to the mode-specific stream via the bus
    client, bypassing the default BaseModule `<module>.out` routing
    (`self.publish` is never called) — there is no aggregate `lingua.out`
    stream; consumers must subscribe to `lingua.external` and/or
    `lingua.internal` explicitly.
    """

    name: ClassVar[str] = "lingua"

    def holds_external_resources(self) -> bool:
        return True

    def __init__(
        self,
        bus: AsyncBus,
        *,
        chat_client: Optional[ChatClient] = None,
        renderer: Optional[FaithfulRenderer] = None,
        intent_log: Optional[IntentExpressionLog] = None,
        chat_url: str = "http://127.0.0.1:11434/v1",
        model_id: str = "kaineone/Qwen3.5-4B-abliterated-GGUF",
        temperature: float = 0.7,
        max_tokens: int = 512,
        think: Optional[bool] = False,
        request_timeout_s: float = 60.0,
        api_key: Optional[str] = None,
        intent_log_path: Path | str = "state/lingua/intent_expression.jsonl",
        assembler: Optional[ContextAssembler] = None,
        self_model_provider: Optional[Callable[[], dict[str, Any]]] = None,
        context_max_events: int = 8,
        context_char_budget: int = 2000,
        persona_name: Optional[str] = None,
        persona_external: Optional[str] = None,
        persona_internal: Optional[str] = None,
        baseline_salience: float = 0.4,
        alert_salience: float = 0.7,
        intent_stream: str = VOLITION_STREAM,
    ) -> None:
        super().__init__(bus)
        if not 0.0 <= baseline_salience <= 1.0:
            raise ValueError("baseline_salience must be in [0, 1]")
        if not 0.0 <= alert_salience <= 1.0:
            raise ValueError("alert_salience must be in [0, 1]")
        self._chat_client: ChatClient = chat_client or OpenAIChatClient(
            base_url=chat_url, timeout_s=request_timeout_s, api_key=api_key
        )
        self._intent_log = intent_log or IntentExpressionLog(intent_log_path)
        self._model_id = model_id
        self._think = think
        self._temperature = float(temperature)
        self._max_tokens = int(max_tokens)
        # The conscious workspace conditions every generation. Lingua caches the
        # latest broadcast it observed (via _snapshot_cache_loop) and renders it
        # into the prompt at speak/think time — the rolling-latest pattern
        # vox uses for thymos.state. The assembler builds (system, prompt)
        # from the persona + that working memory + the triggering input.
        self._assembler = assembler or ContextAssembler(
            renderer,  # None → assembler builds its own renderer
            max_events=context_max_events,
            char_budget=context_char_budget,
            persona_name=persona_name,
            persona_external=persona_external,
            persona_internal=persona_internal,
        )
        self._self_model_provider = self_model_provider
        self._latest_snapshot: Optional[WorkspaceSnapshot] = None
        self._baseline_salience = float(baseline_salience)
        self._alert_salience = float(alert_salience)
        self._intent_stream = intent_stream
        self._intent_cursor = "0-0"

    def set_self_model_provider(
        self, provider: Callable[[], dict[str, Any]]
    ) -> None:
        """Inject a read-only accessor for the Eidolon self-model (wired in
        build_registry). Returns the persona-seeding dict; absent → minimal."""
        self._self_model_provider = provider

    def _self_model(self) -> dict[str, Any]:
        if self._self_model_provider is None:
            return {}
        try:
            return self._self_model_provider() or {}
        except Exception:
            return {}

    async def _snapshot_cache_loop(self) -> None:
        """Passively cache the latest conscious coalition for prompt assembly.

        This NEVER acts — Lingua stays intent-driven, speaking only via volition
        intents. It is deliberately separate from ``on_workspace`` (which stays
        the BaseModule no-op) so Lingua introduces no reflexive workspace
        trigger; this loop just remembers what was conscious so a later ``speak``
        / ``think`` intent can be conditioned on it.
        """
        while not self._stopped.is_set():
            try:
                async for _entry_id, payload in self._bus.subscribe_workspace(last_id="$"):
                    if self._stopped.is_set():
                        break
                    try:
                        snap = self._snapshot_from_payload(payload)
                    except Exception:
                        log.debug("lingua snapshot cache decode failed", exc_info=True)
                        continue
                    # Only cache non-inhibited coalitions: the entity speaks from
                    # what it was consciously, non-inhibitedly aware of.
                    if not snap.inhibited:
                        self._latest_snapshot = snap
            except asyncio.CancelledError:
                raise
            except Exception:
                # Transient bus error: log once and re-subscribe after a short
                # backoff rather than freezing _latest_snapshot forever.
                log.warning("lingua snapshot cache loop error; restarting", exc_info=True)
                try:
                    await asyncio.wait_for(self._stopped.wait(), timeout=0.5)
                except asyncio.TimeoutError:
                    pass

    @property
    def chat_client(self) -> ChatClient:
        return self._chat_client

    @property
    def intent_log(self) -> IntentExpressionLog:
        return self._intent_log

    async def initialize(self) -> None:
        # Seek to the latest intent entry so we only realize intents formed
        # after boot, mirroring Audio Out's dedicated-loop cursor seeding.
        try:
            latest = await self._bus.client.xrevrange(self._intent_stream, count=1)
        except Exception:
            latest = []
        if latest:
            entry_id = latest[0][0]
            if isinstance(entry_id, bytes):
                entry_id = entry_id.decode()
            self._intent_cursor = entry_id
        await super().initialize()
        self._tasks.append(
            asyncio.create_task(self._intent_loop(), name=f"{self.name}-intent")
        )
        self._tasks.append(
            asyncio.create_task(
                self._snapshot_cache_loop(), name=f"{self.name}-snapshot-cache"
            )
        )

    async def shutdown(self) -> None:
        await super().shutdown()
        try:
            await self._chat_client.aclose()
        except Exception:
            log.warning("lingua chat client close failed", exc_info=True)

    async def speak(
        self,
        about: str,
        snapshot: Optional[WorkspaceSnapshot] = None,
    ) -> str:
        # `about` is the triggering input (a user utterance for external speech);
        # the LLM prompt is assembled from it plus the conscious workspace.
        return await self._produce(
            about=about,
            snapshot=snapshot,
            mode="external",
            stream=EXTERNAL_STREAM,
        )

    async def think(
        self,
        about: str,
        snapshot: Optional[WorkspaceSnapshot] = None,
    ) -> str:
        return await self._produce(
            about=about,
            snapshot=snapshot,
            mode="internal",
            stream=INTERNAL_STREAM,
        )

    async def _intent_loop(self) -> None:
        """Realize action intents off ``volition.out``.

        Lingua is intent-driven, NOT reflexive: it never decides on its own to
        respond to perceived input. The only trigger for external speech is a
        ``speak`` intent from the executive action-selection step (which is
        gated by inhibition). ``think`` intents drive internal speech.
        """
        try:
            while not self._stopped.is_set():
                try:
                    entries = await self._bus.read(
                        self._intent_stream,
                        last_id=self._intent_cursor,
                        count=32,
                        block_ms=0,
                    )
                except Exception:
                    await asyncio.sleep(0.05)
                    continue
                if entries:
                    self._intent_cursor = entries[-1][0]
                    for _, event in entries:
                        await self._handle_intent(event)
                else:
                    await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            raise

    async def _handle_intent(self, event: Event) -> None:
        kind = str(event.payload.get("kind") or "")
        about = str(event.payload.get("about") or "")
        if not about:
            return
        try:
            if kind == SPEAK:
                await self.speak(about)
            elif kind == THINK:
                await self.think(about)
        except Exception:
            log.exception("lingua failed to realize %s intent", kind)

    async def _produce(
        self,
        *,
        about: str,
        snapshot: Optional[WorkspaceSnapshot],
        mode: str,
        stream: str,
    ) -> str:
        # Use the explicitly-passed snapshot (tests/direct callers) if given,
        # else the rolling-latest conscious coalition.
        snap = snapshot if snapshot is not None else self._latest_snapshot
        ctx = self._assembler.assemble(
            about=about,
            snapshot=snap,
            self_model=self._self_model(),
            mode=mode,
        )
        request = ChatRequest(
            prompt=ctx.prompt,
            model=self._model_id,
            system=ctx.system,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            think=self._think,
        )
        response = await self._chat_client.complete(request)
        # The same rendered working memory that conditioned the prompt is logged
        # for the A/B comparison (only when a real coalition was present).
        faithful = ctx.working_memory if snap is not None else None
        try:
            self._intent_log.append(
                mode=mode,
                prompt=ctx.prompt,
                generated_text=response.text,
                model=response.model,
                faithful_rendering=faithful,
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
                latency_ms=response.latency_ms,
            )
        except Exception:
            log.exception("intent log append failed")
        payload: dict[str, Any] = {
            "text": response.text,
            "mode": mode,
            "model": response.model,
            "prompt_length": len(ctx.prompt),
            "latency_ms": response.latency_ms,
        }
        # External speech carries the triggering user input so the A/B divergence
        # observer can build its bare baseline. Internal data: eval logs only,
        # never the user-facing conversation surface.
        if mode == "external" and about:
            payload["user_input"] = about
        if faithful is not None:
            payload["faithful_rendering"] = faithful
        # Publish directly to the mode-specific stream (bypassing the
        # default <module>.out routing) so subscribers can filter cleanly.
        await self._bus.client.xadd(
            stream,
            {
                "source": self.name,
                # Semantic speech type (external_speech / internal_speech) so the
                # conversation surface and evaluation observers filter cleanly.
                # mode is "external"/"internal"; the stream is the transport.
                "type": f"{mode}_speech",
                "salience": repr(self._baseline_salience),
                "timestamp": _now_iso(),
                "causal_parent": "",
                "payload": _json(payload),
            },
            maxlen=self._bus.config.default_maxlen,
            approximate=True,
        )
        return response.text


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _json(obj: Any) -> str:
    import json

    return json.dumps(obj, separators=(",", ":"))
