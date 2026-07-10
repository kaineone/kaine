# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""PerceptionLocus — applies entity-initiated perceptual-locus switches.

The operator sets the locus directly through Nexus; this module is the path by
which the *entity* may switch its own locus, via an `intent.perception.switch`
intent from volition. Every such switch is gated (policy + operator lock +
inhibition + minimum dwell), audited onto the bus, and — when applied — writes
the new locus to perception desired-state so Topos/Audio-In rebind (the real
camera/mic go dark on a move to `virtual`).

**Producer gap (deferred virtual-world embodiment):** The `intent.perception.switch`
event type consumed by this module has no producer yet. Volition only emits
`intent.speak`, `intent.think`, and `intent.act`; nothing in the current build
emits `intent.perception.switch`. As a result the entity-initiated self-switch
path cannot fire from the entity. The `allow_self_switch` config knob (default
``False``) is reserved for deferred virtual-world embodiment work and should
remain ``False`` until that work lands. Locus changes are operator-driven (via
Nexus desired-state writes) until then.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, ClassVar, Optional

from kaine import perception_state as ps
from kaine.cycle.types import WorkspaceSnapshot
from kaine.entity_clock import EntityClock
from kaine.modules.base import BaseModule
from kaine.workspace.volition import VOLITION_STREAM

log = logging.getLogger(__name__)

_SWITCH_TYPE = "intent.perception.switch"


class PerceptionLocus(BaseModule):
    name: ClassVar[str] = "perception"

    def __init__(
        self,
        bus,
        *,
        allow_self_switch: bool = False,
        min_dwell_s: float = 30.0,
        intent_stream: str = VOLITION_STREAM,
        desired_path: Optional[Path | str] = None,
        # Shared subjective clock (injected at boot). The minimum-dwell timer is
        # the entity's attentional dwell — a cognitive interval — so it runs in
        # subjective time: at time_scale != 1.0 the dwell dilates with the mind.
        # Defaults to a real-time clock → behavior-identical.
        entity_clock: Optional[EntityClock] = None,
    ) -> None:
        super().__init__(bus)
        self._allow_self_switch = bool(allow_self_switch)
        self._min_dwell_s = float(min_dwell_s)
        self._intent_stream = intent_stream
        self._desired_path = Path(desired_path) if desired_path else None
        self._intent_cursor = "0-0"
        self._inhibited = False
        self._clock = entity_clock or EntityClock()
        # allow the first switch immediately
        self._last_switch_at = self._clock.now() - self._min_dwell_s - 1.0
        self._tasks: list[asyncio.Task] = []

    async def initialize(self) -> None:
        try:
            latest = await self._bus.client.xrevrange(self._intent_stream, count=1)
            self._intent_cursor = latest[0][0] if latest else "0-0"
        except Exception:
            self._intent_cursor = "0-0"
        await super().initialize()
        self._tasks.append(
            asyncio.create_task(self._intent_loop(), name="perception-intent")
        )

    async def shutdown(self) -> None:
        for t in self._tasks:
            t.cancel()
        await super().shutdown()

    async def on_workspace(self, snapshot: WorkspaceSnapshot) -> None:
        # Belt-and-suspenders: volition already suppresses intents while
        # inhibited, but track it so the switch policy can refuse independently.
        self._inhibited = bool(getattr(snapshot, "inhibited", False))

    async def _intent_loop(self) -> None:
        while True:
            try:
                entries = await self._bus.read(
                    self._intent_stream, last_id=self._intent_cursor,
                    count=16, block_ms=200)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("perception: intent read failed")
                await asyncio.sleep(0.5)
                continue
            if not entries:
                continue
            self._intent_cursor = entries[-1][0]
            for _id, event in entries:
                if event.type == _SWITCH_TYPE:
                    await self._handle_switch(event)

    async def _handle_switch(self, event: Any) -> None:
        requested = str((event.payload or {}).get("locus"))
        d = ps.read_desired(self._desired_path)
        since = self._clock.now() - self._last_switch_at
        allowed, reason = ps.evaluate_locus_switch(
            requested,
            current=d.locus,
            locked=d.locus_locked,
            allow_self_switch=self._allow_self_switch,
            inhibited=self._inhibited,
            since_last_switch_s=since,
            min_dwell_s=self._min_dwell_s,
        )
        if allowed:
            ps.write_desired_locus(requested, path=self._desired_path)
            self._last_switch_at = self._clock.now()
            await self.publish(
                "perception.locus.changed",
                {"locus": requested, "by": "entity"}, salience=0.5)
            log.info("perception: entity switched locus -> %s", requested)
        else:
            await self.publish(
                "perception.locus.denied",
                {"requested": requested, "reason": reason}, salience=0.3)
            log.info("perception: denied self-switch -> %s (%s)", requested, reason)
