# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Hearing stage publisher for the stimulus source audio band."""
from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from kaine.boot.perception_feed import _hearing_band_params
from kaine.bus.schema import Event
from kaine.bus.streams import DEVELOPMENT_SOURCE
from kaine.modules.audition.hearing_band import (
    HearingBandParams,
    band_edges,
    hearing_stage,
)

HEARING_STAGE_TYPE = "development.hearing_stage"

log = logging.getLogger(__name__)


class HearingStageWatch:
    def __init__(
        self,
        bus: Any,
        awake: Callable[[], float],
        params: HearingBandParams,
        *,
        period_s: float = 1.0,
    ) -> None:
        if not math.isfinite(period_s) or period_s <= 0.0:
            raise ValueError(f"period_s must be finite and > 0; got {period_s!r}")
        self._bus = bus
        self._awake = awake
        self._params = params
        self._period_s = period_s
        self._last_stage: int | None = None
        self._pending: list[dict[str, Any]] = []

    def _format_band(self, edges: tuple[float | None, float | None]) -> str:
        low, high = edges
        if low is not None and high is not None:
            return f"{low:.1f} to {high:.1f} Hz"
        if low is None and high is not None:
            return f"below {high:.1f} Hz"
        return "open"

    def check(self) -> dict[str, Any] | None:
        t = self._awake()
        stage = hearing_stage(t, self._params)
        if stage == self._last_stage:
            return None
        edges = band_edges(t, self._params)
        band_text = self._format_band(edges)
        log.info(
            "stimulus source: hearing stage %d of 4 (%s) at %.0f s awake",
            stage,
            band_text,
            t,
        )
        payload = {
            "stage": stage,
            "previous_stage": self._last_stage,
            "low_hz": edges[0],
            "high_hz": edges[1],
            "awake_seconds": float(t),
        }
        self._last_stage = stage
        return payload

    async def run(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                payload = self.check()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning("hearing stage check failed", exc_info=True)
                payload = None

            if payload is not None:
                self._pending.append(payload)

            while self._pending:
                event = Event(
                    source=DEVELOPMENT_SOURCE,
                    type=HEARING_STAGE_TYPE,
                    payload=self._pending[0],
                    salience=0.05,
                    timestamp=datetime.now(timezone.utc),
                )
                try:
                    await self._bus.publish(event)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.warning("hearing stage publish failed", exc_info=True)
                    break
                else:
                    self._pending.pop(0)
                    if event.payload["stage"] == 4 and not self._pending:
                        return

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self._period_s)
            except asyncio.TimeoutError:
                continue

    @classmethod
    def from_config(
        cls, kaine_config: dict[str, Any], bus: Any
    ) -> "HearingStageWatch | None":
        if not (kaine_config.get("modules") or {}).get("audition"):
            return None
        feed = kaine_config.get("perception_feed") or {}
        awake_provider = feed.get("_stimulus_source_lived_seconds")
        if awake_provider is None or not callable(awake_provider):
            return None
        try:
            params = _hearing_band_params(feed)
        except ValueError:
            log.warning(
                "invalid hearing band parameters in configuration; not starting watch",
                exc_info=True,
            )
            return None
        if not params.enabled:
            return None
        return cls(bus, awake_provider, params)
