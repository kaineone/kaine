# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""CSRF / Origin / Host-header validation for Nexus.

Mounted as a FastAPI middleware. The ``Host`` header is validated on **every**
request, including read-only GET/HEAD/OPTIONS surfaces, to prevent DNS-rebinding
attacks from extracting data via endpoints such as ``/diagnostics/metrics.json``
or ``/``. State-changing requests are additionally validated against the
configured ``Origin`` allowlist.

Cross-origin or DNS-rebinding requests are rejected with 403. The middleware is
intentionally separate from authentication so both gates must be passed
independently.
"""

from __future__ import annotations

import ipaddress
import logging
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from kaine.nexus.config import NexusConfig

log = logging.getLogger(__name__)

# HTTP methods that can mutate state. GET/HEAD/OPTIONS are assumed safe.
_STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class NexusCSRFError(HTTPException):
    """Raised when a request fails Origin/Host validation."""

    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _is_loopback(host: str) -> bool:
    """True for 127.0.0.1, ::1, and localhost."""
    if host.lower() in {"127.0.0.1", "localhost", "::1"}:
        return True
    try:
        addr = ipaddress.ip_address(host.split("%", 1)[0])
        return addr.is_loopback
    except ValueError:
        return False


def _parse_host(value: str) -> str | None:
    """Parse a Host header value, returning the bare host lower-cased.

    Handles ``name``, ``name:port``, ``1.2.3.4:port``, ``[::1]`` and
    ``[::1]:port``. Returns ``None`` for malformed values such as ``[::1``,
    an empty string, or a port that is not numeric.
    """
    value = value.strip()
    if not value:
        return None

    if value.startswith("["):
        close = value.find("]")
        if close == -1:
            return None
        host = value[1:close].lower()
        remainder = value[close + 1 :]
        if remainder and not remainder.startswith(":"):
            return None
        return host

    if "[" in value or "]" in value:
        return None

    if ":" in value:
        host_part, port_part = value.split(":", 1)
        if not host_part or not port_part.isdigit():
            return None
        return host_part.lower()

    return value.lower()


def _origin_matches(origin: str, allowed: tuple[str, ...]) -> bool:
    parsed = urlparse(origin)
    if parsed.scheme not in {"http", "https"}:
        return False
    netloc = parsed.netloc.lower()
    for allowed_origin in allowed:
        allowed_parsed = urlparse(allowed_origin)
        if allowed_parsed.netloc.lower() == netloc:
            return True
    return False


def _host_allowed(host: str, allowlist: tuple[str, ...]) -> bool:
    """True when the parsed host is in the allowlist.

    Allowlist entries may be written with or without brackets for IPv6
    (e.g. ``::1`` or ``[::1]``); brackets are normalised away.
    """
    parsed = _parse_host(host)
    if parsed is None:
        return False
    allowed = {entry.strip("[]").lower() for entry in allowlist}
    return parsed in allowed


class NexusCSRFMiddleware(BaseHTTPMiddleware):
    """Origin/Host validation middleware for Nexus requests."""

    def __init__(self, app: Any, config: NexusConfig) -> None:
        super().__init__(app)
        self._config = config

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        try:
            self._validate(request)
        except NexusCSRFError as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
                headers=exc.headers or {},
            )
        return await call_next(request)

    def _validate(self, request: Request) -> None:
        # Host-header validation applies to every request.
        host = request.headers.get("host")
        if host is None:
            if _is_loopback(self._config.host):
                return
            log.warning("nexus csrf: rejected request without Host header")
            raise NexusCSRFError("host not allowed")

        if not _host_allowed(host, self._config.host_allowlist):
            log.warning("nexus csrf: rejected request with host=%r", host)
            raise NexusCSRFError("host not allowed")

        # State-changing methods additionally require Origin validation.
        if request.method not in _STATE_CHANGING_METHODS:
            return

        origin = request.headers.get("Origin")
        if not origin:
            return
        if _origin_matches(origin, self._config.allowed_origins):
            return

        log.warning("nexus csrf: rejected cross-origin request")
        raise NexusCSRFError("cross-origin request rejected")
