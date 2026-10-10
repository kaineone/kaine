# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, ClassVar, Optional

from kaine.bus.client import AsyncBus
from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.defaults import DEFAULT_CHAT_URL
from kaine.faithful import FaithfulRenderer
from kaine.faithful.external_input import EXTERNAL_INPUT_TYPES, iter_text_leaves
from kaine.faithful.templates import HEARD_SPEECH_PLACEHOLDER, HEARD_TEXT_FIELDS
from kaine.modules.base import BaseModule
from kaine.modules.lingua.client import (
    ChatClient,
    ChatRequest,
    OpenAIChatClient,
)
from kaine.modules.lingua.context import PERSONA_TEMPLATE_VERSION, ContextAssembler
from kaine.modules.lingua.intent_log import IntentExpressionLog
from kaine.persistence.system_prompts import digest_of, store_dir_for, write_system_prompt
from kaine.storage import resolve
from kaine.workspace.volition import SPEAK, THINK, VOLITION_STREAM

log = logging.getLogger(__name__)

EXTERNAL_STREAM: str = "lingua.external"
INTERNAL_STREAM: str = "lingua.internal"

#: The bus stream + event type carrying Eidolon's self-model snapshot. Lingua
#: consumes this over the bus to seed its persona, so the language organ can run
#: in a separate process / on a separate trusted host from Eidolon instead of
#: holding an in-process reference to it (``distributed-deployment``).
EIDOLON_OUT_STREAM: str = "eidolon.out"
EIDOLON_SELF_MODEL_TYPE: str = "eidolon.self_model"


class Lingua(BaseModule):
    """Language organ - the LLM speaks *from* workspace access, not from
    the bare triggering text.

    Every generation is conditioned by a `ContextAssembler` that builds the
    `(system, prompt)` pair from a first-person persona (seeded from the Eidolon
    self-model) + a rendering of the current accessed coalition + the triggering
    input - the `persona ∪ working-memory ∪ input` shape from CoALA / Generative
    Agents / GWA. Lingua caches the latest broadcast it observed via a passive
    `_snapshot_cache_loop` (it stays intent-driven and never reflexively speaks;
    `on_workspace` remains the BaseModule no-op). External-speech events also
    carry `user_input`, but only when the trigger is a tagged felt-state phrase
    or event summary; heard speech is never published. This lets the A/B
    divergence observer measure how much the cognitive scaffolding moves the
    output versus a bare-LLM baseline for non-heard triggers.

    Lingua's bus output goes to two distinct streams. `speak` writes the
    user-facing channel that Chatterbox subscribes to. `think` writes the
    internal-monologue channel that Mnemos consumes and Eidolon counts but
    Chatterbox NEVER reads.

    `_produce()` writes to the mode-specific stream via the bus client,
    then mirrors the same event to the canonical aggregate `lingua.out`
    stream through `self.publish`. Consumers that need to distinguish
    external from internal speech subscribe to the split streams; generic
    observers and the nexus diagnostics tail can follow `lingua.out`.
    """

    name: ClassVar[str] = "lingua"
    relieves_drives: ClassVar[frozenset[str]] = frozenset({"boredom", "social_drive"})

    def holds_external_resources(self) -> bool:
        return True

    def set_lora_resolver(self, resolver) -> None:
        """Attach a per-request LoRA resolver if the chat client supports it."""
        client = self._chat_client
        if hasattr(client, "set_lora_resolver"):
            client.set_lora_resolver(resolver)
        else:
            log.info(
                "lingua backend %r does not support per-request adapters",
                type(client).__name__,
            )

    def __init__(
        self,
        bus: AsyncBus,
        *,
        chat_client: Optional[ChatClient] = None,
        renderer: Optional[FaithfulRenderer] = None,
        intent_log: Optional[IntentExpressionLog] = None,
        chat_url: str = DEFAULT_CHAT_URL,
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
        self._intent_log = intent_log or IntentExpressionLog(resolve(intent_log_path))
        self._stored_system_digests: set[str] = set()
        self._model_id = model_id
        self._think = think
        self._temperature = float(temperature)
        self._max_tokens = int(max_tokens)
        # Workspace access conditions every generation. Lingua caches the
        # latest broadcast it observed (via _snapshot_cache_loop) and renders it
        # into the prompt at speak/think time - the rolling-latest pattern
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
        self._persona_digest = hashlib.sha256(
            json.dumps([persona_name, persona_external, persona_internal]).encode("utf-8")
        ).hexdigest()[:16]
        # Latest self-model snapshot observed on eidolon.out (bus-mediated persona
        # seed). Preferred over the in-process provider so Lingua can run split
        # from Eidolon; None until the first snapshot arrives (fresh boot → the
        # minimal persona, exactly as an empty in-process model would give).
        self._bus_self_model: Optional[dict[str, Any]] = None
        self._latest_snapshot: Optional[WorkspaceSnapshot] = None
        # Situation facts held by Lingua when no Eidolon self-model carries them.
        self._own_situation_facts: list[str] = []
        # Whether an Eidolon self-model is expected for this being.
        self._expects_self_model = True
        self._baseline_salience = float(baseline_salience)
        self._alert_salience = float(alert_salience)
        self._intent_stream = intent_stream
        self._intent_cursor = "0-0"
        # Latest Hypnos sleep index observed on hypnos.out (None until seen).
        self._sleep_index: Optional[int] = None
        self._hypnos_cursor = "0-0"
        # The single in-flight generation, held as a cancellable task so an
        # urgent (interrupt-marked) speak intent can preempt it mid-stream
        # instead of the loop awaiting it to completion (interruptible-utterance
        # D1). None when nothing is being realized; ``_gen_mode`` records which
        # channel it is on so a preemption can be logged content-free.
        self._gen_task: Optional[asyncio.Task[Any]] = None
        self._gen_mode: Optional[str] = None
        # generation bookkeeping for the individuation probe's yield-to-speech rule
        self._produce_in_flight = 0
        self._last_produce_end: Optional[float] = None

    def set_self_model_provider(self, provider: Callable[[], dict[str, Any]]) -> None:
        """Inject a read-only accessor for the Eidolon self-model (wired in
        build_registry). Returns the persona-seeding dict; absent → minimal."""
        self._self_model_provider = provider

    def set_expects_self_model(self, expected: bool) -> None:
        """Whether an Eidolon self-model is part of this being; when False, the probe conditions on a minimal self-model instead of waiting for a snapshot that never comes."""
        self._expects_self_model = expected

    async def add_situation_fact(self, text: str) -> bool:
        """A fact about the being's situation that Lingua renders in its persona when no Eidolon self-model carries it. It is held in memory and re-given at every boot."""
        text = text.strip()
        if not text:
            raise ValueError("situation fact cannot be empty")
        if text in self._own_situation_facts:
            return False
        self._own_situation_facts.append(text)
        return True

    def _with_own_facts(self, sm: dict) -> dict:
        merged = dict(sm)
        if not self._own_situation_facts:
            return merged
        situation_facts = list(merged.get("situation_facts") or [])
        for fact in self._own_situation_facts:
            if fact not in situation_facts:
                situation_facts.append(fact)
        merged["situation_facts"] = situation_facts
        return merged

    def _self_model(self) -> dict[str, Any]:
        # Prefer the bus-mediated snapshot (works single-host AND split-host).
        # Fall back to an injected in-process provider only when no snapshot has
        # been observed yet (e.g. a test that wires a provider directly).
        if self._bus_self_model is not None:
            return self._with_own_facts(dict(self._bus_self_model))
        if self._self_model_provider is None:
            return self._with_own_facts({})
        try:
            return self._with_own_facts(self._self_model_provider() or {})
        except Exception:
            return self._with_own_facts({})

    async def _self_model_cache_loop(self) -> None:
        """Cache the latest Eidolon self-model snapshot published on eidolon.out.

        This is the bus-mediated replacement for the former in-process
        ``_wire_lingua_self_model`` accessor: Lingua seeds its persona from the
        self-model *snapshot* Eidolon publishes rather than reaching into the
        live Eidolon object, so the two modules may run in different processes /
        on different trusted hosts sharing one authenticated bus. Only the
        persona-seeding fields are kept (no cognitive text is retained).
        """
        # Read from the stream head so a snapshot already published at boot (the
        # Eidolon initial publish) seeds the persona immediately; the stream is
        # low-volume (one self-model snapshot per identity update).
        cursor = "0-0"
        while not self._stopped.is_set():
            try:
                entries, last_scanned = await self._bus.read_entries(
                    EIDOLON_OUT_STREAM, last_id=cursor, count=32, block_ms=0
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                try:
                    await asyncio.wait_for(self._stopped.wait(), timeout=0.2)
                except asyncio.TimeoutError:
                    # no stop signal within the backoff window; keep polling
                    pass
                continue
            if last_scanned is not None:
                cursor = last_scanned
                for _entry_id, ev in entries:
                    if ev.type == EIDOLON_SELF_MODEL_TYPE:
                        self._bus_self_model = {
                            "name": ev.payload.get("name"),
                            "values": list(ev.payload.get("values", []) or []),
                            "behavioral_norms": list(ev.payload.get("behavioral_norms", []) or []),
                            "situation_facts": list(ev.payload.get("situation_facts", []) or []),
                            "personality_baseline": dict(
                                ev.payload.get("personality_baseline", {}) or {}
                            ),
                        }
            else:
                try:
                    await asyncio.wait_for(self._stopped.wait(), timeout=0.1)
                except asyncio.TimeoutError:
                    # no stop signal yet; keep polling the stream
                    pass

    async def _hypnos_cache_loop(self) -> None:
        """Cache the latest completed sleep index published on hypnos.out.

        The index is the number of sleeps Hypnos has completed since it
        started, stamped on its hypnos.out events. Lingua records the latest
        value it has seen, or None before any such event (unknown, never 0).
        """
        cursor = self._hypnos_cursor
        while not self._stopped.is_set():
            try:
                entries, last_scanned = await self._bus.read_entries(
                    "hypnos.out", last_id=cursor, count=32, block_ms=0
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                try:
                    await asyncio.wait_for(self._stopped.wait(), timeout=0.2)
                except asyncio.TimeoutError:
                    pass
                continue
            if last_scanned is not None:
                cursor = last_scanned
                self._hypnos_cursor = cursor
                for _entry_id, ev in entries:
                    idx = ev.payload.get("sleep_index")
                    if isinstance(idx, int) and not isinstance(idx, bool):
                        # The latest value, not the largest: a restarted Hypnos
                        # counts from zero again, and the record must say so.
                        self._sleep_index = idx
            else:
                try:
                    await asyncio.wait_for(self._stopped.wait(), timeout=0.1)
                except asyncio.TimeoutError:
                    pass

    async def _snapshot_cache_loop(self) -> None:
        """Passively cache the latest accessed coalition for prompt assembly.

        This NEVER acts - Lingua stays intent-driven, speaking only via volition
        intents. It is deliberately separate from ``on_workspace`` (which stays
        the BaseModule no-op) so Lingua introduces no reflexive workspace
        trigger; this loop just remembers what was accessed so a later ``speak``
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
                    # what was accessed and not inhibited.
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
                    # Expected: the wait is just the backoff before re-subscribing,
                    # not a shutdown request — timing out means keep looping.
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

        # Seed the Hypnos sleep-index cursor from the stream tail, then scan
        # the most recent events to catch the latest sleep_index published
        # before boot. Never use "$": a non-blocking read from "$" never returns.
        try:
            latest_hypnos = await self._bus.client.xrevrange("hypnos.out", count=1)
        except Exception:
            latest_hypnos = []
        if latest_hypnos:
            entry_id = latest_hypnos[0][0]
            if isinstance(entry_id, bytes):
                entry_id = entry_id.decode()
            self._hypnos_cursor = entry_id
        try:
            recent_hypnos = await self._bus.client.xrevrange("hypnos.out", count=200)
        except Exception as exc:
            log.debug("hypnos sleep_index backfill failed: %s", exc)
            recent_hypnos = []
        # xrevrange is newest first: the first sleep_index found is the latest.
        for _entry_id, fields in recent_hypnos:
            raw = fields.get("payload", fields.get(b"payload"))
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            try:
                hypnos_payload = json.loads(raw) if raw else {}
            except (TypeError, ValueError):
                continue
            idx = hypnos_payload.get("sleep_index") if isinstance(hypnos_payload, dict) else None
            if isinstance(idx, int) and not isinstance(idx, bool):
                self._sleep_index = idx
                break

        await super().initialize()
        self._tasks.append(asyncio.create_task(self._intent_loop(), name=f"{self.name}-intent"))
        self._tasks.append(
            asyncio.create_task(self._snapshot_cache_loop(), name=f"{self.name}-snapshot-cache")
        )
        self._tasks.append(
            asyncio.create_task(self._self_model_cache_loop(), name=f"{self.name}-self-model-cache")
        )
        self._tasks.append(
            asyncio.create_task(self._hypnos_cache_loop(), name=f"{self.name}-hypnos-cache")
        )

    async def shutdown(self) -> None:
        await super().shutdown()
        try:
            await self._chat_client.aclose()
        except Exception:
            log.warning("lingua chat client close failed", exc_info=True)

    def probe_self_model(self) -> dict | None:
        """The self-model the probe conditions on; None until Eidolon's snapshot has arrived, or a minimal model when no Eidolon self-model is expected."""
        if self._bus_self_model is not None:
            return self._with_own_facts(dict(self._bus_self_model))
        if not self._expects_self_model:
            return self._with_own_facts({"values": [], "behavioral_norms": []})
        return None

    def is_idle(self, quiet_s: float) -> bool:
        """True when no utterance is being generated and none finished in the last ``quiet_s`` seconds."""
        if self._produce_in_flight > 0:
            return False
        if self._gen_task is not None and not self._gen_task.done():
            return False
        if self._last_produce_end is not None and time.monotonic() - self._last_produce_end < quiet_s:
            return False
        return True

    def probe_conditions(self) -> dict[str, Any]:
        """The fixed generation conditions of the individuation probe (no content)."""
        return {
            "model_id": self._model_id,
            "temperature": self._temperature,
            "think": self._think,
            "persona_digest": self._persona_digest,
            "persona_template_version": PERSONA_TEMPLATE_VERSION,
        }

    def probe_request(self, about: str, *, seed: int, max_tokens: int, self_model: dict) -> ChatRequest:
        """Build the individuation probe's request under fixed conditions.

        Working memory is empty and the current self-model seeds the persona.
        Side-effect free: it never writes the intent log, publishes nothing and
        never enters the being's experience.
        """
        ctx = self._assembler.assemble(
            about=about, snapshot=None, self_model=self_model, mode="external"
        )
        return ChatRequest(
            prompt=ctx.prompt,
            model=self._model_id,
            system=ctx.system,
            temperature=self._temperature,
            max_tokens=int(max_tokens),
            think=self._think,
            seed=int(seed),
            cache_prompt=False,
        )

    async def speak(
        self,
        about: str,
        snapshot: Optional[WorkspaceSnapshot] = None,
        *,
        origin: Optional[Any] = None,
        intent_entry_id: Optional[str] = None,
        about_kind: Optional[str] = None,
    ) -> str:
        # `about` is the triggering input (a user utterance for external speech);
        # the LLM prompt is assembled from it plus workspace access.
        return await self._produce(
            about=about,
            snapshot=snapshot,
            mode="external",
            stream=EXTERNAL_STREAM,
            origin=origin,
            intent_entry_id=intent_entry_id,
            about_kind=about_kind,
        )

    async def think(
        self,
        about: str,
        snapshot: Optional[WorkspaceSnapshot] = None,
        *,
        origin: Optional[Any] = None,
        intent_entry_id: Optional[str] = None,
        about_kind: Optional[str] = None,
    ) -> str:
        return await self._produce(
            about=about,
            snapshot=snapshot,
            mode="internal",
            stream=INTERNAL_STREAM,
            origin=origin,
            intent_entry_id=intent_entry_id,
            about_kind=about_kind,
        )

    async def _intent_loop(self) -> None:
        """Realize action intents off ``volition.out``.

        Lingua is intent-driven, NOT reflexive: it never decides on its own to
        respond to perceived input. The only trigger for external speech is a
        ``speak`` intent from the executive action-selection step (which is
        gated by inhibition). ``think`` intents drive internal speech.

        Each generation runs as a held, cancellable task rather than an inline
        ``await`` (interruptible-utterance D1). The loop keeps reading intents
        while a generation is in flight, so an interrupt-marked ``speak`` can be
        detected and preempt the current utterance (real async cancellation,
        never a post-hoc discard). Ordinary intents queue behind the in-flight
        generation — one language organ produces one token stream.
        """
        try:
            while not self._stopped.is_set():
                try:
                    entries, last_scanned = await self._bus.read_entries(
                        self._intent_stream,
                        last_id=self._intent_cursor,
                        count=32,
                        block_ms=0,
                    )
                except Exception:
                    await asyncio.sleep(0.05)
                    continue
                if last_scanned is not None:
                    self._intent_cursor = last_scanned
                    for _, event in entries:
                        await self._dispatch_intent(event)
                else:
                    await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            # Shutdown: never leak an in-flight generation past the loop.
            await self._cancel_gen_task()
            raise

    async def _dispatch_intent(self, event: Event) -> None:
        """Route one intent event to a (possibly preempting) generation task."""
        kind = str(event.payload.get("kind") or "")
        about = str(event.payload.get("about") or "")
        origin = event.payload.get("origin")
        entry_id = event.payload.get("entry_id")
        about_kind = event.payload.get("about_kind")
        if kind == "rest":
            log.debug("ignoring rest intent")
            return
        if not about or kind not in (SPEAK, THINK):
            return
        # Only a `speak` may interrupt; `think` never preempts outer speech.
        interrupt = kind == SPEAK and bool(event.payload.get("interrupt"))
        if self._gen_task is not None and not self._gen_task.done():
            if interrupt:
                # A more salient intent won the workspace: cancel the in-flight
                # utterance and redirect. Real cancellation — the unspoken
                # remainder is never generated or published.
                self._gen_task.cancel()
                await self._settle_gen_task()
            else:
                # One token stream: let the in-flight generation finish before
                # starting the next. Non-interrupt intents queue, never overlap.
                await self._settle_gen_task()
        self._gen_mode = "external" if kind == SPEAK else "internal"
        self._gen_task = asyncio.create_task(
            self._realize_intent(
                kind, about, origin, intent_entry_id=entry_id, about_kind=about_kind
            ),
            name=f"{self.name}-gen",
        )

    async def _realize_intent(
        self,
        kind: str,
        about: str,
        origin: Optional[Any] = None,
        *,
        intent_entry_id: Optional[str] = None,
        about_kind: Optional[str] = None,
    ) -> None:
        """Produce one utterance. Runs as the held ``_gen_task``; a preempting
        interrupt cancels it, which propagates ``CancelledError`` out of the
        in-flight ``complete()`` call (the natural cancellation point)."""
        try:
            kwargs: dict[str, Any] = {}
            if origin is not None:
                kwargs["origin"] = origin
            if intent_entry_id is not None:
                kwargs["intent_entry_id"] = intent_entry_id
            if about_kind is not None:
                kwargs["about_kind"] = about_kind
            if kind == SPEAK:
                await self.speak(about, **kwargs)
            elif kind == THINK:
                await self.think(about, **kwargs)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("lingua failed to realize %s intent", kind)
            # C3: content-free realization-failed audit event — mode and
            # reason class ONLY; never the text, prompt, or any payload that
            # was headed for generation. Guards are cleared by the
            # refractory-scaled timeouts in the workspace policies; this
            # event is the observability trail.
            try:
                await self._write_mode_record(
                    INTERNAL_STREAM,
                    "realization_failed",
                    {"mode": kind, "reason_class": type(exc).__name__},
                )
            except Exception:
                log.warning("lingua: realization_failed publish failed", exc_info=True)

    async def _settle_gen_task(self) -> None:
        """Await the held generation, converting a preemptive cancellation into
        a content-free preemption record and clearing the handle."""
        task = self._gen_task
        if task is None:
            return
        mode = self._gen_mode
        # Clear the handle up front so the outer-cancellation branch can cancel
        # the still-running task without re-entrant handle confusion.
        self._gen_task = None
        self._gen_mode = None
        try:
            await task
        except asyncio.CancelledError:
            if task.cancelled():
                # Preempted mid-utterance (redirect): discard the unspoken
                # remainder and note a content-free preemption (D4). A partial
                # already published stays published — we do not un-say it.
                self._record_preemption(mode)
            else:
                # Outer (shutdown) cancellation raced in while the generation was
                # still running — cancel it so it can't leak, then propagate.
                task.cancel()
                try:
                    await task
                except (Exception, asyncio.CancelledError):
                    # Swallow whatever the settling task raises (its own
                    # cancellation or a cleanup error); the bare ``raise`` below
                    # re-raises the outer cancellation we are still handling.
                    pass
                raise
        except Exception:
            log.exception("lingua generation task failed")

    async def _cancel_gen_task(self) -> None:
        """Best-effort cancel of any in-flight generation (shutdown path)."""
        task = self._gen_task
        self._gen_task = None
        self._gen_mode = None
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except (Exception, asyncio.CancelledError):
            # Best-effort settle of the cancelled task; shutdown propagation is
            # handled by the caller's own re-raise.
            pass

    def _record_preemption(self, mode: Optional[str]) -> None:
        tick = getattr(self._latest_snapshot, "tick_index", None)
        try:
            self._intent_log.record_preemption(mode=mode or "external", tick=tick)
        except Exception:
            log.exception("lingua preemption record failed")

    async def _write_mode_record(self, stream: str, type_: str, payload: dict[str, Any]) -> None:
        await self._bus.client.xadd(
            stream,
            {
                "source": self.name,
                "type": type_,
                "salience": repr(self._baseline_salience),
                "timestamp": _now_iso(),
                "causal_parent": "",
                "payload": _json(payload),
            },
            maxlen=self._bus.config.default_maxlen,
            approximate=True,
        )

    async def _produce(
        self,
        *,
        about: str,
        snapshot: Optional[WorkspaceSnapshot],
        mode: str,
        stream: str,
        origin: Optional[Any] = None,
        intent_entry_id: Optional[str] = None,
        about_kind: Optional[str] = None,
    ) -> str:
        """Wrap _produce_inner with in-flight bookkeeping."""
        self._produce_in_flight += 1
        try:
            return await self._produce_inner(
                about=about,
                snapshot=snapshot,
                mode=mode,
                stream=stream,
                origin=origin,
                intent_entry_id=intent_entry_id,
                about_kind=about_kind,
            )
        finally:
            self._produce_in_flight -= 1
            self._last_produce_end = time.monotonic()

    async def _produce_inner(
        self,
        *,
        about: str,
        snapshot: Optional[WorkspaceSnapshot],
        mode: str,
        stream: str,
        origin: Optional[Any] = None,
        intent_entry_id: Optional[str] = None,
        about_kind: Optional[str] = None,
    ) -> str:
        # Use the explicitly-passed snapshot (tests/direct callers) if given,
        # else the rolling-latest accessed coalition.
        snap = snapshot if snapshot is not None else self._latest_snapshot

        def _iter_field_values(value, fields):
            if isinstance(value, dict):
                for k, v in value.items():
                    if k in fields:
                        if isinstance(v, str):
                            stripped = v.strip()
                            if stripped:
                                yield stripped
                        elif isinstance(v, (dict, list, tuple)):
                            yield from iter_text_leaves(v)
                    elif isinstance(v, (dict, list, tuple)):
                        yield from _iter_field_values(v, fields)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    yield from _iter_field_values(item, fields)

        # Heard speech is anything that came from an external-input event in
        # the coalition (audition.transcription, mundus.chat), plus any unmarked
        # about (fail-closed: felt/event must be explicitly tagged). The
        # redaction set also holds the values of the heard-speech payload fields
        # at any depth on any coalition event.
        heard_texts: set[str] = set()
        redact_texts: set[str] = set()
        # Heard-field values from events other than Lingua's own. Lingua's own
        # earlier user_input is a felt or event phrase it chose to publish.
        foreign_field_texts: set[str] = set()
        if snap is not None:
            for _entry_id, event in snap.selected_events:
                if event.type in EXTERNAL_INPUT_TYPES:
                    for leaf in iter_text_leaves(event.payload):
                        heard_texts.add(leaf)
                for leaf in _iter_field_values(
                    event.payload, HEARD_TEXT_FIELDS - {"text"}
                ):
                    redact_texts.add(leaf)
                    if event.source != "lingua":
                        foreign_field_texts.add(leaf)
        redact_texts |= heard_texts

        # Only an external-input event makes an about heard. Field values (for
        # example a felt phrase Lingua itself published as user_input) are
        # redacted from the log but never decide how the trigger is framed.
        about_is_heard = (
            about_kind not in ("felt", "event") or about.strip() in heard_texts
        )

        ctx = self._assembler.assemble(
            about=about,
            snapshot=snap,
            self_model=self._self_model(),
            mode=mode,
            about_is_heard=about_is_heard,
        )
        request = ChatRequest(
            prompt=ctx.prompt,
            model=self._model_id,
            system=ctx.system,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            think=self._think,
            seed=None,
        )
        response = await self._chat_client.complete(request)

        # The log is the training corpus of the being's own utterances. Heard
        # speech never reaches it: prompt and faithful rendering are redacted.
        logged_prompt = ctx.logged_prompt
        logged_faithful = ctx.logged_working_memory if snap is not None else None
        for heard in redact_texts:
            if len(heard) >= 3:
                logged_prompt = logged_prompt.replace(heard, HEARD_SPEECH_PLACEHOLDER)
                if logged_faithful is not None:
                    logged_faithful = logged_faithful.replace(
                        heard, HEARD_SPEECH_PLACEHOLDER
                    )
        if logged_prompt != ctx.logged_prompt or (
            logged_faithful is not None and logged_faithful != ctx.logged_working_memory
        ):
            log.warning("heard speech placeholder applied to residual text in log")

        record_id = uuid.uuid4().hex
        system_digest = digest_of(ctx.system)
        try:
            store_dir = store_dir_for(self._intent_log.path)
            if system_digest not in self._stored_system_digests:
                write_system_prompt(store_dir, ctx.system)
                self._stored_system_digests.add(system_digest)
        except Exception:
            log.exception("system prompt store failed")

        try:
            self._intent_log.append(
                mode=mode,
                prompt=logged_prompt,
                generated_text=response.text,
                model=response.model,
                faithful_rendering=logged_faithful,
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
                latency_ms=response.latency_ms,
                record_id=record_id,
                intent_entry_id=intent_entry_id,
                intent_origin=origin,
                sleep_index=self._sleep_index,
                system_digest=system_digest,
                seed=request.seed,
            )
        except Exception:
            log.exception("intent log append failed")

        # Bus payloads use the same redacted faithful rendering that was
        # persisted; user_input is carried only for tagged felt/event triggers,
        # never for heard speech.
        payload: dict[str, Any] = {
            "text": response.text,
            "mode": mode,
            "model": response.model,
            "prompt_length": len(ctx.prompt),
            "latency_ms": response.latency_ms,
            "record_id": record_id,
        }
        if origin is not None:
            payload["origin"] = origin
        if mode == "external" and about and not about_is_heard:
            # A felt or event about can still repeat heard text found in the
            # coalition (an external input, or a heard field on another
            # module's event); that text is redacted before publishing.
            published_about = about
            for heard in heard_texts | foreign_field_texts:
                if len(heard) >= 3:
                    published_about = published_about.replace(
                        heard, HEARD_SPEECH_PLACEHOLDER
                    )
            payload["user_input"] = published_about
        faithful = logged_faithful
        if faithful is not None:
            payload["faithful_rendering"] = faithful
        # Publish directly to the mode-specific stream (bypassing the
        # default <module>.out routing) so subscribers can filter cleanly.
        await self._write_mode_record(stream, f"{mode}_speech", payload)
        # Also publish to the aggregate lingua.out stream so consumers that
        # expect the canonical <module>.out routing (nexus diagnostics, raw
        # archive, generic observers) see every utterance in one place.
        # Bypass `self.publish` to avoid driving the oscillator; Lingua's
        # mode-specific xadd above is the activity signal the oscillatory layer
        # already observes.
        from kaine.bus.schema import validate_event

        await self._bus.publish(
            validate_event(
                source=self.name,
                type=f"{mode}_speech",
                payload=payload,
                salience=self._baseline_salience,
                timestamp=datetime.now(timezone.utc),
            )
        )
        return response.text


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _json(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"))
