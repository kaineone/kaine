# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Mundus — the body-agnostic embodiment control plane.

Mundus routes the entity's perception and action to and from a *body* through a
pluggable :class:`~kaine.modules.mundus.adapter.EmbodimentAdapter`. The core owns
the entity-facing contract — gating, locus, intent routing, the speech mirror,
salience policy, and zero-raw-sense-data persistence — and knows nothing about
any wire protocol. Each body (the transport-free ``stub`` reference body today, a
virtual world, VR runtime, or robot later) is a separate adapter, selected in
config and injected here; adding a body never touches this core.

Incoming perception (``FeedFrame``s from the adapter) becomes ``mundus.*`` bus
events; ``intent.avatar.*`` intents from Volition become symbolic actions, and
(future) continuous setpoints become graded channel commands, both routed to the
adapter's sinks. So the live cognitive loop perceives and acts through the body,
not a script.

Two-layer safety gate (mirrors voice-alignment / paracosm-connector): requires
both ``[mundus].enabled = true`` in config and ``KAINE_MUNDUS_OPERATOR_APPROVED=1``
in the environment. Per-action-family exposure flags gate world-mutating verbs;
continuous channels gate per-channel and default unexposed.

This module never blocks the cognitive cycle: all body I/O runs in its own
asyncio tasks; bus publishes are fire-and-forget.

**Producer gap — closed as continuous control:** The ``_intent_loop`` consumes
``intent.avatar.*`` events from the Volition stream. Symbolic verb families still
have no producer wired into the entity's learned policy (they remain operator-only
tools). The *continuous* producer gap, however, is closed by
``intuitive-embodiment-control-surface``: the
:class:`~kaine.modules.mundus.control_surface.ContinuousMotorSurface` emits a
per-tick ``intent.avatar.control`` carrying the continuous channel scalars, which
this module routes to the continuous setpoint sink (``_drive_control`` →
:meth:`apply_setpoints`, clamped and per-channel gated) and mirrors back as an
efference copy (``mundus.efference``) time-aligned with the outgoing action so the
forward model can close the loop. The ``_speech_loop`` — mirroring
``lingua.external`` text into local chat — also remains live. The exposure flags
still gate which families/channels are allowed.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING, Any, Callable, ClassVar, Optional

from kaine import perception_state
from kaine.modules.base import BaseModule
from kaine.modules.mundus.adapter import EmbodimentAdapter, FeedFrame
from kaine.modules.mundus.channels import CONTINUOUS_CHANNEL_RANGE
from kaine.workspace.volition import VOLITION_STREAM

if TYPE_CHECKING:
    # Imported for typing only — the control surface is injected at construction,
    # so the core never needs it at runtime.
    from kaine.modules.mundus.control_surface import ContinuousMotorSurface

log = logging.getLogger(__name__)

_AVATAR_PREFIX = "intent.avatar."
# The continuous control intent (`intuitive-embodiment-control-surface`): the
# entity's per-tick motor command, carrying the continuous channel scalars under
# `payload["channels"]`. It is NOT a symbolic action family — it is routed to the
# continuous setpoint sink, not `apply_action`, and drives the body directly.
_CONTROL_ACTION = "control"


def operator_approved() -> bool:
    return os.environ.get("KAINE_MUNDUS_OPERATOR_APPROVED") == "1"


class Mundus(BaseModule):
    name: ClassVar[str] = "mundus"

    def __init__(
        self,
        bus,
        *,
        adapter: EmbodimentAdapter,
        enabled: bool = False,
        expose: Optional[dict[str, bool]] = None,
        continuous_expose: Optional[dict[str, bool]] = None,
        mirror_speech: bool = True,
        speech_stream: str = "lingua.external",
        intent_stream: str = VOLITION_STREAM,
        locus_reader: Optional[Callable[[], str]] = None,
        control_surface: Optional["ContinuousMotorSurface"] = None,
    ) -> None:
        super().__init__(bus)
        self._adapter = adapter
        # The continuous motor producer (the entity's per-tick learned policy +
        # freeze-then-free curriculum + closed-loop forward model). Held here so
        # the control plane and its producer are constructed together and the
        # producer is reachable; the per-tick driving loop is the cycle's motor
        # seam (`intuitive-embodiment-control-surface`), not started by the
        # control plane. None until wired — the surface is inert without it.
        self._control_surface = control_surface
        caps = adapter.capabilities()
        # The body only acts when the entity's perceptual locus is `virtual`.
        self._locus_reader = locus_reader or (lambda: perception_state.read_desired().locus)
        self._config_enabled = bool(enabled)
        # Symbolic exposure: descriptor defaults, overridden by operator config.
        self._expose = {**dict(caps.action_families), **(expose or {})}
        # Continuous exposure: every declared channel defaults UNEXPOSED (like the
        # disruptive verbs), overridable per channel by config.
        overrides = continuous_expose or {}
        self._continuous_expose = {
            channel: bool(overrides.get(channel, False))
            for channel in caps.continuous_channels
        }
        self._mirror_speech = bool(mirror_speech)
        self._speech_stream = speech_stream
        self._intent_stream = intent_stream
        self._intent_cursor = "0-0"
        self._speech_cursor = "0-0"
        self._tasks: list[asyncio.Task] = []

    @property
    def control_surface(self) -> Optional["ContinuousMotorSurface"]:
        """The continuous motor producer, if one was wired (else None)."""
        return self._control_surface

    def _enabled(self) -> bool:
        return self._config_enabled and operator_approved()

    async def initialize(self) -> None:
        if not self._enabled():
            log.info("mundus disabled (config=%s, operator_approved=%s)",
                     self._config_enabled, operator_approved())
            return
        # Only act on intents/speech formed AFTER we come up.
        self._intent_cursor = await self._latest_id(self._intent_stream)
        self._speech_cursor = await self._latest_id(self._speech_stream)
        await super().initialize()
        await self._adapter.open()
        log.info("mundus control plane up on body %r",
                 self._adapter.capabilities().name)
        self._tasks.append(asyncio.create_task(self._feed_loop(), name="mundus-feed"))
        self._tasks.append(asyncio.create_task(self._intent_loop(), name="mundus-intent"))
        if self._mirror_speech:
            self._tasks.append(
                asyncio.create_task(self._speech_loop(), name="mundus-speech"))

    async def shutdown(self) -> None:
        for t in self._tasks:
            t.cancel()
        await self._adapter.close()
        await super().shutdown()

    async def _latest_id(self, stream: str) -> str:
        try:
            latest = await self._bus.client.xrevrange(stream, count=1)
            return latest[0][0] if latest else "0-0"
        except Exception:
            return "0-0"

    # ---- perception: body → KAINE -----------------------------------------
    async def _feed_loop(self) -> None:
        try:
            async for frame in self._adapter.feed():
                await self._handle_feed(frame)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("mundus: feed loop failed")

    async def _handle_feed(self, frame: FeedFrame) -> None:
        caps = self._adapter.capabilities()
        mapping = caps.feed_events.get(frame.kind)
        if mapping is None:
            log.debug("mundus: unknown feed kind %r", frame.kind)
            return
        event_type, salience = mapping
        payload = dict(frame.payload)
        # Zero raw-sense-data persistence: strip every raw buffer the body's
        # descriptor names (e.g. the rendered frame buffer) before it can reach
        # the bus or disk; only metadata rides the event.
        for key in caps.raw_buffer_keys:
            payload.pop(key, None)
        # Bump salience on notable events (core-owned salience policy).
        if frame.kind == "proprio" and (payload.get("dying") or payload.get("falling")):
            salience = 0.8
        elif frame.kind == "entity" and payload.get("arrived"):
            salience = 0.5
        await self.publish(event_type, payload, salience=salience)

    # ---- action: KAINE → body ---------------------------------------------
    async def _send_action(self, family: str, **params: Any) -> bool:
        """Route one symbolic action to the body, gated by locus + exposure."""
        if self._locus_reader() != "virtual":
            log.debug("mundus: locus not virtual; not acting in-world (%r)", family)
            return False
        if not self._expose.get(family, False):
            log.info("mundus: action %r not exposed; dropped", family)
            return False
        try:
            return await self._adapter.apply_action(family, params)
        except Exception:
            log.exception("mundus: failed to send action %r", family)
            return False

    async def apply_setpoints(self, channels: dict[str, float]) -> bool:
        """Route continuous setpoints to the body's continuous sink.

        Each channel is gated per-channel (default unexposed) and by locus, and
        clamped to its declared range at the boundary (the producer is never
        trusted). A body that declares no continuous channels rejects the whole
        request as unsupported (the sink returns False and the core logs it),
        mirroring the "family not exposed" path.
        """
        caps = self._adapter.capabilities()
        if not caps.continuous_channels:
            ok = await self._adapter.apply_setpoints(dict(channels))
            if not ok:
                log.info("mundus: body %r has no continuous sink; setpoints "
                         "unsupported", caps.name)
            return ok
        if self._locus_reader() != "virtual":
            log.debug("mundus: locus not virtual; not driving setpoints")
            return False
        gated = self._gate_channels(channels)
        if not gated:
            return False
        try:
            return await self._adapter.apply_setpoints(gated)
        except Exception:
            log.exception("mundus: failed to apply setpoints")
            return False

    def _gate_channels(self, channels: dict[str, float]) -> dict[str, float]:
        """Gate + clamp continuous channels: on-body, per-channel exposure, range.

        The producer is never trusted — an unknown channel, an unexposed channel,
        or an out-of-range value is respectively dropped or clamped here, at the
        boundary. Returns the channels that survive gating, clamped to range.
        """
        caps = self._adapter.capabilities()
        gated: dict[str, float] = {}
        for name, value in channels.items():
            if name not in caps.continuous_channels:
                log.info("mundus: channel %r not on this body; dropped", name)
                continue
            if not self._continuous_expose.get(name, False):
                log.info("mundus: channel %r not exposed; dropped", name)
                continue
            lo, hi = CONTINUOUS_CHANNEL_RANGE.get(name, (-1.0, 1.0))
            gated[name] = max(lo, min(hi, float(value)))
        return gated

    async def _drive_control(self, channels: dict[str, float]) -> bool:
        """Route one continuous control tick (`intent.avatar.control`) to the body.

        Drives the gated/clamped setpoints AND publishes the efference copy — the
        scalars the entity emitted (clamped to range) — onto the bus time-aligned
        with the outgoing action, so the forward model can predict -> compare ->
        correct against the coupled proprioceptive/visual feedback (which arrives
        via the body's own feed as `mundus.proprio` / `mundus.visual.*`). Feedback
        is mandatory, not optional: the efference copy is what makes the surface a
        closed loop rather than an open-loop joystick.
        """
        forwarded = await self.apply_setpoints(channels)
        # Efference copy of the EMITTED command (clamped), regardless of which
        # channels were gated off — it is a copy of what the entity emitted, not
        # of what reached the body.
        efference: dict[str, float] = {}
        for name, value in channels.items():
            if name not in CONTINUOUS_CHANNEL_RANGE:
                continue
            lo, hi = CONTINUOUS_CHANNEL_RANGE[name]
            efference[name] = max(lo, min(hi, float(value)))
        await self.publish(
            "mundus.efference",
            {"channels": efference, "forwarded": bool(forwarded)},
            salience=0.2,
        )
        return forwarded

    async def _intent_loop(self) -> None:
        while True:
            try:
                entries = await self._bus.read(
                    self._intent_stream, last_id=self._intent_cursor,
                    count=32, block_ms=200)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("mundus: intent read failed")
                await asyncio.sleep(0.5)
                continue
            if not entries:
                continue
            self._intent_cursor = entries[-1][0]
            for _id, event in entries:
                if event.type.startswith(_AVATAR_PREFIX):
                    family = event.type[len(_AVATAR_PREFIX):]
                    if family == _CONTROL_ACTION:
                        # Continuous per-tick motor command → setpoint sink, NOT
                        # the symbolic `apply_action` path. This is the producer
                        # gap closed as continuous control.
                        channels = (event.payload or {}).get("channels") or {}
                        if isinstance(channels, dict):
                            await self._drive_control(
                                {str(k): float(v) for k, v in channels.items()})
                        continue
                    await self._send_action(family, **(event.payload or {}))

    async def _speech_loop(self) -> None:
        """Mirror KAINE's external speech out the body's local chat, so the
        entity is conversational in-world before volition produces avatar
        intents directly. (intent.avatar.say from volition still works too.)"""
        while True:
            try:
                entries = await self._bus.read(
                    self._speech_stream, last_id=self._speech_cursor,
                    count=16, block_ms=200)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("mundus: speech read failed")
                await asyncio.sleep(0.5)
                continue
            if not entries:
                continue
            self._speech_cursor = entries[-1][0]
            for _id, event in entries:
                text = (event.payload or {}).get("text")
                if text:
                    await self._send_action("say", message=str(text), channel=0)

    def serialize(self) -> dict[str, Any]:
        return {"intent_cursor": self._intent_cursor, "speech_cursor": self._speech_cursor}

    def deserialize(self, state: dict[str, Any]) -> None:
        self._intent_cursor = state.get("intent_cursor", self._intent_cursor)
        self._speech_cursor = state.get("speech_cursor", self._speech_cursor)
