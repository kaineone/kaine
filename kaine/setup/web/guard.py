# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Host/Origin validation and the running-cycle check for the setup server."""
from __future__ import annotations

import errno
import json
import os
import socket
from pathlib import Path

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import PlainTextResponse, Response

from kaine.bus.config import load_bus_config, load_bus_endpoint
from kaine.bus.cycle_presence import cycle_on_bus
from kaine.bus.errors import BusConfigError
from kaine.lifecycle.liveness import cycle_process_details

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


def _runtime_file_reason(path: Path) -> tuple[bool | None, str | None]:
    """Check the runtime file.  Returns ``(True, reason)`` when running,
    ``(False, None)`` when the file says not running, and ``(None, None)``
    when the file is missing or inconclusive so the bus should be asked.
    """
    if not path.exists():
        return (None, None)

    try:
        data = json.loads(path.read_text())
    except Exception:
        return (True, "runtime file exists but cannot be read; failing closed")

    pid = data.get("pid")
    if not isinstance(pid, int):
        return (True, "runtime file does not contain a valid pid; failing closed")

    permission_error = False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return (None, None)
    except PermissionError:
        # Process exists but we cannot verify its identity; unless the
        # cmdline positively identifies kaine.cycle we must fail closed.
        permission_error = True
    except (OSError, ValueError):
        return (True, "cannot verify recorded cycle pid; failing closed")

    cmdline_path = Path(f"/proc/{pid}/cmdline")
    try:
        cmdline = cmdline_path.read_text().replace("\x00", " ")
    except Exception:
        return (True, "cannot read recorded cycle cmdline; failing closed")

    if "kaine.cycle" in cmdline or permission_error:
        return (True, "runtime file shows a live kaine.cycle process")

    return (None, None)


def _probe_endpoint(host: str, port: int) -> bool | None:
    """Return ``True`` if the endpoint is listening, ``False`` if the
    connection was refused, or ``None``/raise when the state is unknown.
    """
    try:
        with socket.create_connection((host, port), timeout=1.0):
            pass
    except ConnectionRefusedError:
        return False
    except OSError as exc:
        if exc.errno == errno.ECONNREFUSED:
            return False
        raise
    except Exception:
        raise
    return True


def _bus_reason(path: Path) -> tuple[bool, str | None]:
    """Ask the bus when the runtime file says the local entity is not running."""
    try:
        bus_cfg = load_bus_config()
    except BusConfigError:
        try:
            host, port = load_bus_endpoint()
        except Exception as exc:
            return (
                True,
                f"the bus configuration cannot be read here ({type(exc).__name__}); "
                "cannot rule out a running entity, so saving is refused",
            )
        try:
            listening = _probe_endpoint(host, port)
        except Exception as exc:
            return (
                True,
                f"the bus at {host}:{port} could not be probed ({type(exc).__name__}); "
                "cannot rule out a running entity",
            )
        if listening is False:
            return (False, None)
        if listening is True:
            return (
                True,
                f"the bus at {host}:{port} is running but its credentials are not available to this shell; "
                "cannot rule out a running entity. Run setup where config/secrets.toml "
                "holds the bus password, or export KAINE_REDIS_PASSWORD "
                "(for a compose install, its value is in compose/.env), or stop the entity first",
            )
        return (
            True,
            f"the bus at {host}:{port} could not be probed (unknown); cannot rule out a running entity",
        )
    except Exception as exc:
        return (
            True,
            f"bus configuration could not be loaded ({type(exc).__name__})",
        )

    alive, detail = cycle_on_bus(bus_cfg)
    if alive is True:
        return (True, detail)
    if alive is None:
        return (
            True,
            detail or "bus probe could not determine cycle state; failing closed",
        )
    return (False, None)


def _process_check() -> tuple[bool | None, int | None, list[str] | None]:
    """The host process scan, as ``(state, pid, argv)``."""
    return cycle_process_details()


def cycle_running_with_reason(
    state_root: Path | None = None,
) -> tuple[bool, str | None]:
    """Return ``(running, reason)`` for a live KAINE cycle.

    The check reads ``state/cycle/runtime.json`` first (resolved via
    ``kaine.storage.resolve`` when no ``state_root`` is supplied).  When the
    runtime file says the entity is not running, the host is also scanned for a
    live ``kaine.cycle`` process (which is visible from the host even for
    containerized cycles).  Finally, the shared bus is queried so that cycles
    in other containers are detected.  A recycled PID is rejected if
    ``/proc/<pid>/cmdline`` does not contain ``kaine.cycle``.

    Fail-closed: any doubt counts as running, because a running entity must
    never have its config rewritten.
    """
    if state_root is not None:
        path = state_root / "cycle" / "runtime.json"
    else:
        try:
            from kaine.storage import resolve

            path = resolve("state/cycle/runtime.json")
        except Exception:
            path = Path("state/cycle/runtime.json")

    running, reason = _runtime_file_reason(path)
    if running is True:
        return (True, reason)

    proc_state, proc_pid, proc_argv = _process_check()
    if proc_state is True:
        if proc_pid is not None and proc_argv:
            argv_text = " ".join(proc_argv)
            if len(argv_text) > 200:
                argv_text = argv_text[:200] + "..."
            reason = (
                f"a kaine.cycle process is running on this host "
                f"(pid {proc_pid}: {argv_text})"
            )
        else:
            reason = "a kaine.cycle process is running on this host"
        return (True, reason)
    if proc_state is None:
        return (
            True,
            "the host's process list could not be fully read; cannot rule out a running entity",
        )

    return _bus_reason(path)


def cycle_running(state_root: Path | None = None) -> bool:
    """Return ``True`` if a live KAINE cycle is recorded or connected."""
    return cycle_running_with_reason(state_root)[0]
