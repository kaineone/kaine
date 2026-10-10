# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Probe the shared bus for a running KAINE cycle."""
from __future__ import annotations

import errno
import logging
import time
from typing import Any

from kaine.bus.client import CYCLE_CLIENT_NAME
from kaine.bus.schema import WORKSPACE_STREAM

log = logging.getLogger("kaine.bus.cycle_presence")

# A broadcast this recent means a cycle ran moments ago; wider than the
# runtime-file window because a sleeping or dilated cycle broadcasts less often.
BUS_FRESH_SECONDS = 60.0


def _is_connection_refused(exc: Exception) -> bool:
    """Walk an exception chain looking for ECONNREFUSED."""
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, ConnectionRefusedError):
            return True
        if isinstance(exc, OSError) and exc.errno == errno.ECONNREFUSED:
            return True
        # Some Redis clients wrap the underlying OSError in ``args``.
        for arg in getattr(exc, "args", ()):
            if isinstance(arg, ConnectionRefusedError):
                return True
            if isinstance(arg, OSError) and arg.errno == errno.ECONNREFUSED:
                return True
        exc = exc.__cause__ or exc.__context__
    return False


def cycle_on_bus(bus_cfg: Any) -> tuple[bool | None, str]:
    """Ask the shared bus whether a KAINE cycle is connected or recently broadcast.

    Returns ``(True, detail)`` if a cycle client is connected or a recent
    workspace broadcast exists, ``(False, detail)`` if the bus is known to be
    down or the stream is empty/stale, and ``(None, detail)`` if the server
    could not be queried.  The URL and password from ``bus_cfg`` are never
    included in the returned text.
    """
    client = None
    try:
        import redis

        client = redis.Redis.from_url(
            bus_cfg.url,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
        )
        try:
            client.ping()
        except Exception as exc:
            if _is_connection_refused(exc):
                return (
                    False,
                    "the bus is not running (connection refused); no cycle can be connected to it",
                )
            return (None, f"bus unreachable ({type(exc).__name__})")

        try:
            for c in client.client_list():
                if c.get("name") == CYCLE_CLIENT_NAME:
                    return (True, "a KAINE cycle is connected to the bus")
        except Exception as exc:
            return (None, f"cannot list bus clients ({type(exc).__name__})")

        entries = client.xrevrange(WORKSPACE_STREAM, count=1)
        if not entries:
            return (False, f"{WORKSPACE_STREAM} has no broadcast")
        entry_id, _fields = entries[0]
        id_str = entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)
        ms = int(id_str.split("-")[0])
        age_s = time.time() - ms / 1000.0
        if age_s < BUS_FRESH_SECONDS:
            return (True, f"{WORKSPACE_STREAM} last broadcast {age_s:.0f} s ago")
        return (
            False,
            f"{WORKSPACE_STREAM} has no recent broadcast (last {age_s:.0f} s ago)",
        )
    except Exception as exc:
        return (None, f"bus unreachable ({type(exc).__name__})")
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                log.debug("bus client close failed", exc_info=True)
