# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""OpenSim embodiment adapter — the transitional reference body.

This is a pure lift of the pre-refactor OpenSim/LEAP bridge: it owns the
localhost TCP listener the LEAP shim (running inside the forked Firestorm viewer)
connects out to, speaks the same length-prefixed-MessagePack wire protocol
(:mod:`kaine.modules.mundus.bridge`), keeps the same single-connection
"newest wins" semantics, and emits the same action frames with a fresh
``reqid``. Perception flows shim → KAINE as :class:`FeedFrame`s the core maps to
``mundus.*`` events; symbolic action frames flow KAINE → shim.

The adapter is symbolic/autopilot only (``continuous_channels=()``): it has no
graded control sink, so it rejects continuous setpoints as unsupported. It is
marked ``transitional`` — the seam's conformance body, retired once a real
VR/paracosm adapter exists (design §10.1).

Behavior is preserved bit-for-bit against the old ``Mundus`` module; the feed→event
map and default exposures live in :mod:`kaine.modules.mundus.bridge` and a test
asserts the descriptor equals those constants so any drift fails CI.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, AsyncIterator, Optional

from kaine.modules.mundus.adapter import EmbodimentCapabilities, FeedFrame
from kaine.modules.mundus.bridge import (
    ACTION_DEFAULT_EXPOSED,
    FEED_EVENT,
    read_frame,
    write_frame,
)

log = logging.getLogger(__name__)


class OpenSimAdapter:
    """Drives a KAINE avatar in an OpenSim grid through the LEAP shim bridge."""

    def __init__(self, host: str = "127.0.0.1", port: int = 7781) -> None:
        self._host = host
        self._port = int(port)
        self._server: Optional[asyncio.AbstractServer] = None
        self._writer: Optional[asyncio.StreamWriter] = None  # the live shim conn
        self._frames: asyncio.Queue[FeedFrame] = asyncio.Queue()

    def capabilities(self) -> EmbodimentCapabilities:
        return EmbodimentCapabilities(
            name="opensim",
            transitional=True,
            feed_events=dict(FEED_EVENT),
            action_families=dict(ACTION_DEFAULT_EXPOSED),
            continuous_channels=(),
            raw_buffer_keys=("data",),
        )

    async def open(self) -> None:
        self._server = await asyncio.start_server(
            self._on_client, self._host, self._port)
        log.info("mundus/opensim bridge listening on %s:%s", self._host, self._port)

    async def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            self._writer = None
        if self._server is not None:
            self._server.close()
            self._server = None

    # ---- bridge: shim → KAINE (perception) --------------------------------
    async def _on_client(self, reader: asyncio.StreamReader,
                         writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        log.info("mundus/opensim: shim connected from %s", peer)
        if self._writer is not None:  # single connection — newest wins
            self._writer.close()
        self._writer = writer
        try:
            while True:
                frame = await read_frame(reader)
                if frame is None:
                    break
                kind = frame.get("kind", "")
                payload = {k: v for k, v in frame.items() if k != "kind"}
                await self._frames.put(FeedFrame(kind=kind, payload=payload))
        except (asyncio.IncompleteReadError, ConnectionError, ValueError) as exc:
            log.info("mundus/opensim: shim connection ended: %s", exc)
        finally:
            if self._writer is writer:
                self._writer = None
            writer.close()

    async def feed(self) -> AsyncIterator[FeedFrame]:
        while True:
            yield await self._frames.get()

    # ---- bridge: KAINE → shim (action) ------------------------------------
    async def apply_action(self, family: str, params: dict[str, Any]) -> bool:
        writer = self._writer
        if writer is None:
            log.debug("mundus/opensim: no shim connected; dropping action %r", family)
            return False
        try:
            await write_frame(writer, {"kind": "action", "action": family,
                                       "reqid": str(uuid.uuid4()), **params})
            return True
        except Exception:
            log.exception("mundus/opensim: failed to send action %r", family)
            return False

    async def apply_setpoints(self, channels: dict[str, float]) -> bool:
        # Symbolic/autopilot body: no continuous sink. Reject as unsupported.
        log.info("mundus/opensim: continuous setpoints unsupported by this body")
        return False
