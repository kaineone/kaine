# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Dev-gated LOOPBACK preview server — the cross-process bridge for the live
perception PiP.

The in-RAM preview holder (:mod:`kaine.perception_preview`) is process-local:
``Topos``/``Audition`` populate it inside the CYCLE process, but Nexus is a
SEPARATE process, so its own holder is always empty. This module closes that gap
in the *purest* way for the load-bearing zero-raw-sense-persistence invariant: it
serves the holder's current single slot over a LOOPBACK socket. Frames never
touch the filesystem — there is no named RAM segment, no temp file, no shared
memory object, only a TCP socket bound to 127.0.0.1 and ``io.BytesIO``.

Design / invariants:

  * DEV-GATED. The server is only started when the operator sets
    ``KAINE_PERCEPTION_PREVIEW=1`` (paper §4.4 explicit override). Off by default
    ⇒ the server never binds and the PiP stays hidden. Every request is *also*
    re-checked against the live flag, so clearing the flag makes it 404.
  * LOOPBACK ONLY. The listener refuses any non-loopback bind address, mirroring
    the bus's refuse-external-binding posture — the preview can never be reached
    off-host.
  * ZERO PERSISTENCE. The handler reads the RAM holder and writes to sockets
    only. It opens no file, in any mode.
  * NON-BLOCKING. It runs on the cycle's own asyncio loop via
    :func:`asyncio.start_server` (one lightweight task per short-lived
    connection) and shuts down cleanly with the cycle.

Routes (minimal, loopback-internal):

  ``GET /video`` → ``image/jpeg`` of the current frame, or ``404`` when the flag
                   is off / no frame is held.
  ``GET /audio`` → ``{"level": <float|null>}`` (metadata only, never PCM).
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from kaine import perception_preview

log = logging.getLogger(__name__)

DEFAULT_PREVIEW_PORT = 8089

# Addresses that keep the listener on-host only. A bind request for anything
# else is refused (mirrors the bus's external-binding refusal).
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def preview_port(config: Optional[dict[str, Any]] = None) -> int:
    """Resolve the loopback preview port from ``[perception_preview].port``.

    Reads the merged kaine config when none is supplied. Falls back to
    :data:`DEFAULT_PREVIEW_PORT` when the section/key is absent or malformed.
    Reads config only (no sense data, no writes).
    """
    if config is None:
        try:
            from kaine.config import load_kaine_config

            config = load_kaine_config()
        except Exception:
            config = {}
    section = config.get("perception_preview") or {}
    try:
        return int(section.get("port", DEFAULT_PREVIEW_PORT))
    except (TypeError, ValueError):
        return DEFAULT_PREVIEW_PORT


def _http_response(
    status: int, reason: str, *, body: bytes, content_type: str
) -> bytes:
    """Encode a minimal HTTP/1.1 response. ``Connection: close`` so the client
    (httpx from the Nexus proxy) does not attempt keep-alive against this
    single-shot handler."""
    head = (
        f"HTTP/1.1 {status} {reason}\r\n"
        f"Content-Type: {content_type}\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Cache-Control: no-store\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).encode("latin-1")
    return head + body


_NOT_FOUND = _http_response(
    404, "Not Found", body=b"not found", content_type="text/plain"
)


class PreviewServer:
    """A tiny loopback HTTP server exposing the in-RAM preview holder.

    Serves ``GET /video`` and ``GET /audio`` from
    :mod:`kaine.perception_preview`. Binds 127.0.0.1 only; opens no file.
    """

    def __init__(
        self,
        *,
        port: int = DEFAULT_PREVIEW_PORT,
        host: str = "127.0.0.1",
        holder: Any = None,
    ) -> None:
        if host not in _LOOPBACK_HOSTS:
            raise ValueError(
                f"perception preview server refuses non-loopback host {host!r}; "
                "the preview is on-host only"
            )
        self._host = host
        self._port = int(port)
        self._holder = holder or perception_preview.holder()
        self._server: Optional[asyncio.AbstractServer] = None

    @property
    def port(self) -> int:
        """The bound port (resolved after :meth:`start` when 0 was requested)."""
        if self._server is not None:
            for sock in self._server.sockets or ():
                try:
                    return int(sock.getsockname()[1])
                except (OSError, IndexError):
                    continue
        return self._port

    @property
    def host(self) -> str:
        return self._host

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle, host=self._host, port=self._port
        )

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:
                log.debug("preview server close raised", exc_info=True)
            self._server = None

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            request_line = await reader.readline()
            # Drain the request headers (we need none of them) up to the blank
            # line so the socket is in a clean state before we reply.
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b"\n", b""):
                    break
            response = self._route(request_line)
            writer.write(response)
            await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            return
        except Exception:
            log.debug("preview server request handling failed", exc_info=True)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                # Best-effort close of a possibly already-broken connection;
                # mirrors the `stop()` server-close pattern above.
                log.debug("preview connection close failed", exc_info=True)

    def _route(self, request_line: bytes) -> bytes:
        try:
            parts = request_line.decode("latin-1").split()
            method, raw_path = parts[0], parts[1]
        except (ValueError, IndexError):
            return _NOT_FOUND
        path = raw_path.split("?", 1)[0]
        if method != "GET":
            return _NOT_FOUND
        # Live dev-gate re-check: clearing the flag makes every route 404 even
        # while the listener is still up.
        if not perception_preview.preview_enabled():
            return _NOT_FOUND
        if path == "/video":
            jpeg = self._holder.get_video_jpeg()
            if not jpeg:
                return _NOT_FOUND
            return _http_response(
                200, "OK", body=bytes(jpeg), content_type="image/jpeg"
            )
        if path == "/audio":
            body = json.dumps(
                {"level": self._holder.get_audio_level()}
            ).encode("utf-8")
            return _http_response(
                200, "OK", body=body, content_type="application/json"
            )
        return _NOT_FOUND


async def start_preview_server(
    *,
    config: Optional[dict[str, Any]] = None,
    port: Optional[int] = None,
    holder: Any = None,
) -> Optional[PreviewServer]:
    """Start the loopback preview server IFF the dev override is set.

    Returns the running server, or ``None`` when ``KAINE_PERCEPTION_PREVIEW`` is
    not ``1`` (the default) — in which case nothing binds and the Nexus proxy
    404s, keeping the PiP hidden.
    """
    if not perception_preview.preview_enabled():
        return None
    resolved_port = port if port is not None else preview_port(config)
    server = PreviewServer(port=resolved_port, holder=holder)
    await server.start()
    return server
