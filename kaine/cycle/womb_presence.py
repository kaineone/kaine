# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Running local womb presence publisher.

A running local womb announces itself from real deliveries, with the same
contract an external provider uses, so the maturation gate checks one
interface for both. Publishes no content, only the provider name and a
frame index.
"""
from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from kaine.bus.schema import Event

if TYPE_CHECKING:
    from kaine.modules.topos.feed import WombClock

PRESENCE_SOURCE = "gestation"
PRESENCE_TYPE = "gestation.womb"

log = logging.getLogger(__name__)


class WombPresencePublisher:
    def __init__(
        self,
        bus: Any,
        clock: "WombClock",
        *,
        period_s: float = 1.0,
        max_staleness_s: float = 2.0,
    ) -> None:
        if not math.isfinite(period_s) or period_s <= 0.0:
            raise ValueError(f"period_s must be finite and > 0; got {period_s!r}")
        if not math.isfinite(max_staleness_s) or max_staleness_s <= 0.0:
            raise ValueError(
                f"max_staleness_s must be finite and > 0; got {max_staleness_s!r}"
            )
        self._bus = bus
        self._clock = clock
        self._period_s = period_s
        self._max_staleness_s = max_staleness_s

    def presence_payload(self) -> dict[str, Any] | None:
        now = self._clock.monotonic()
        video = self._clock.last_delivery("video")
        audio = self._clock.last_delivery("audio")
        if video is None or audio is None:
            return None
        video_t, video_i = video
        audio_t, _audio_i = audio
        if now - video_t > self._max_staleness_s:
            return None
        if now - audio_t > self._max_staleness_s:
            return None
        return {"provider": "local", "frame_index": int(video_i)}

    async def run(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            payload = self.presence_payload()
            if payload is not None:
                event = Event(
                    source=PRESENCE_SOURCE,
                    type=PRESENCE_TYPE,
                    payload=payload,
                    salience=0.05,
                    timestamp=datetime.now(timezone.utc),
                )
                try:
                    await self._bus.publish(event)
                except Exception:
                    log.warning("womb presence publish failed", exc_info=True)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self._period_s)
            except asyncio.TimeoutError:
                pass
