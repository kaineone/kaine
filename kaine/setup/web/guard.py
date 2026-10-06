# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Host/Origin validation and the running-cycle check for the setup server."""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import PlainTextResponse, Response

_STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _split_host_port(value: str) -> tuple[str | None, str | None]:
    """Return ``(host_lower, port_or_none)`` for a Host header value.

    Handles ``name``, ``name:port``, ``1.2.3.4:port``, ``[::1]`` and
    ``[::1]:port``.  Returns ``(None, None)`` for malformed values.
    """
    value = value.strip().lower()
    if not value:
        return (None, None)

    if value.startswith("["):
        close = value.find("]")
        if close == -1:
            return (None, None)
        host = value[1:close]
        rest = value[close + 1 :]
        if not rest:
            return (host, None)
        if rest.startswith(":"):
            port = rest[1:]
            if not port.isdigit():
                return (None, None)
            return (host, port)
        return (None, None)

    if "[" in value or "]" in value:
        return (None, None)

    if ":" in value:
        host_part, port_part = value.rsplit(":", 1)
        if not host_part or not port_part.isdigit():
            return (None, None)
        return (host_part, port_part)

    return (value, None)


class HostOriginMiddleware(BaseHTTPMiddleware):
    """Require loopback Host on every request and loopback Origin on changes."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        host_header = request.headers.get("host")
        if host_header is None:
            return PlainTextResponse("host not allowed", status_code=403)

        actual_port = getattr(request.app.state, "port", None)
        port = actual_port if actual_port is not None else request.url.port
        if port is None:
            # Requests without an explicit port are compared only by name; the
            # browser always sends the port for non-standard loopback origins.
            port = "80" if request.url.scheme == "http" else "443"

        allowed_hosts = {
            ("127.0.0.1", str(port)),
            ("localhost", str(port)),
            ("::1", str(port)),
        }
        host_parsed, host_port = _split_host_port(host_header)
        if host_port is None:
            host_port = str(port)
        if (host_parsed, host_port) not in allowed_hosts:
            return PlainTextResponse("host not allowed", status_code=403)

        if request.method in _STATE_CHANGING_METHODS:
            origin = request.headers.get("origin")
            allowed_origins = {
                f"http://127.0.0.1:{port}",
                f"http://localhost:{port}",
                f"http://[::1]:{port}",
            }
            if origin not in allowed_origins:
                return PlainTextResponse(
                    "cross-origin request rejected", status_code=403
                )

        return await call_next(request)


def cycle_running(state_root: Path | None = None) -> bool:
    """Return ``True`` if a live ``kaine.cycle`` process is recorded.

    The check reads ``state/cycle/runtime.json`` (resolved via
    ``kaine.storage.resolve`` when no ``state_root`` is supplied).  A recycled
    PID is rejected if ``/proc/<pid>/cmdline`` does not contain ``kaine.cycle``.

    Fail-closed: any doubt about a recorded runtime file counts as running,
    because a running entity must never have its config rewritten.
    """
    if state_root is not None:
        path = state_root / "cycle" / "runtime.json"
    else:
        try:
            from kaine.storage import resolve

            path = resolve("state/cycle/runtime.json")
        except Exception:
            path = Path("state/cycle/runtime.json")

    if not path.exists():
        return False

    try:
        data = json.loads(path.read_text())
    except Exception:
        return True

    pid = data.get("pid")
    if not isinstance(pid, int):
        return True

    permission_error = False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we cannot verify its identity; unless the
        # cmdline positively identifies kaine.cycle we must fail closed.
        permission_error = True
    except (OSError, ValueError):
        return True

    cmdline_path = Path(f"/proc/{pid}/cmdline")
    try:
        cmdline = cmdline_path.read_text().replace("\x00", " ")
    except Exception:
        return True

    return "kaine.cycle" in cmdline or permission_error
