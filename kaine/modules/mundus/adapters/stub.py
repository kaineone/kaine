# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Stub embodiment adapter — a transport-free reference body.

This adapter proves body-agnosticism with a second, wholly local body and pins
the protocol — especially the continuous-channel path a real transport-backed
adapter would drive. It has no socket, no wire, no external dependency:

* :meth:`feed` yields nothing by default; tests may inject scripted
  :class:`FeedFrame`s via :meth:`push_frame`;
* :meth:`apply_action` is a no-op that records the call in :attr:`actions`;
* :meth:`apply_setpoints` accepts the five canonical continuous channels and
  records them in :attr:`setpoints`.

It declares symbolic no-op families plus the canonical continuous channels
(``drive``, ``yaw_rate``, ``gaze_yaw``, ``gaze_pitch``, ``interact``) and is
``transitional=False``. It is the shipped reference body and ships off (the
Mundus module is inactive by default) — a reference/test body, not a real one; a
transport-backed virtual-world adapter is planned.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator

from kaine.modules.mundus.adapter import EmbodimentCapabilities, FeedFrame

log = logging.getLogger(__name__)

# Symbolic no-op families the stub exposes by default (so the core can drive the
# symbolic path without any world-mutating consequence).
STUB_ACTION_FAMILIES: dict[str, bool] = {
    "say": True,
    "gesture": True,
}

# The canonical continuous-channel vocabulary (design §10.2).
STUB_CONTINUOUS_CHANNELS: tuple[str, ...] = (
    "drive",
    "yaw_rate",
    "gaze_yaw",
    "gaze_pitch",
    "interact",
)


class StubAdapter:
    """A local, transport-free reference body that records what it is asked to do."""

    def __init__(self) -> None:
        self._frames: asyncio.Queue[FeedFrame] = asyncio.Queue()
        self.opened = False
        self.closed = False
        self.actions: list[tuple[str, dict[str, Any]]] = []
        self.setpoints: list[dict[str, float]] = []

    def capabilities(self) -> EmbodimentCapabilities:
        return EmbodimentCapabilities(
            name="stub",
            transitional=False,
            feed_events={
                "chat": ("mundus.chat", 0.6),
                "proprio": ("mundus.proprio", 0.3),
            },
            action_families=dict(STUB_ACTION_FAMILIES),
            continuous_channels=STUB_CONTINUOUS_CHANNELS,
            raw_buffer_keys=(),
        )

    def push_frame(self, frame: FeedFrame) -> None:
        """Inject a scripted feed frame (for tests)."""
        self._frames.put_nowait(frame)

    async def open(self) -> None:
        self.opened = True

    async def close(self) -> None:
        self.closed = True

    async def feed(self) -> AsyncIterator[FeedFrame]:
        while True:
            yield await self._frames.get()

    async def apply_action(self, family: str, params: dict[str, Any]) -> bool:
        self.actions.append((family, dict(params)))
        log.debug("mundus/stub: recorded action %r %r", family, params)
        return True

    async def apply_setpoints(self, channels: dict[str, float]) -> bool:
        self.setpoints.append(dict(channels))
        log.debug("mundus/stub: recorded setpoints %r", channels)
        return True
