# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""CSRF / Origin / Host-header validation for Nexus.

Mounted as a FastAPI middleware. Validates that state-changing requests either:

1. Originate from an allowed origin (``Origin`` header matches the configured
   allowlist), or
2. Arrive with a Host header that is in the configured host allowlist.

Cross-origin or DNS-rebinding requests are rejected with 403. The middleware
is intentionally separate from authentication so both gates must be passed
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
    host = host.split(":", 1)[0].lower()
    return host in {h.lower() for h in allowlist}


class NexusCSRFMiddleware(BaseHTTPMiddleware):
    """Origin/Host validation middleware for Nexus state-changing requests."""

    def __init__(self, app: Any, config: NexusConfig) -> None:
        super().__init__(app)
        self._config = config

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method in _STATE_CHANGING_METHODS:
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
        origin = request.headers.get("Origin")
        host = request.headers.get("Host", "")

        # If an Origin header is present, it must match the allowlist.
        if origin:
            if _origin_matches(origin, self._config.allowed_origins):
                return
            log.warning("nexus csrf: rejected cross-origin request from %s", origin)
            raise NexusCSRFError("cross-origin request rejected")

        # No Origin header: require a Host header in the allowlist.
        if host and _host_allowed(host, self._config.host_allowlist):
            return

        # Loopback binds are always acceptable when no explicit Host is sent.
        if not host and _is_loopback(self._config.host):
            return

        log.warning("nexus csrf: rejected request with host=%r", host)
        raise NexusCSRFError("host not allowed")
