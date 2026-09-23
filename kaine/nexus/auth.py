# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Operator authentication dependency for Nexus.

A single bearer-token scheme protects every state-changing endpoint and every
privileged read surface. The token is configured in ``NexusConfig.operator_token``
(populated from ``KAINE_NEXUS_TOKEN`` or ``config/secrets.toml``) and is never
logged.

Browser clients that cannot send custom headers authenticate via a short-lived
session cookie established through ``/login``. Because cookies are shared across
all ports of a host, state-changing requests additionally require a per-session
key delivered once at login and sent in ``X-Nexus-Session-Key``.
"""

from __future__ import annotations

import hmac
import logging
import secrets
import threading
import time
import urllib.parse
from collections import OrderedDict
from collections.abc import Callable
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

from kaine.nexus.config import NexusConfig

log = logging.getLogger(__name__)

_AUTH_HEADER_PREFIX = "Bearer "
SESSION_COOKIE = "kaine_nexus_session"
SESSION_KEY_HEADER = "X-Nexus-Session-Key"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_MAX_RATE_LIMIT_KEYS = 1024
_MAX_LOGIN_BODY_BYTES = 4096


class NexusAuthError(HTTPException):
    """Raised when a request lacks a valid operator token or session."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="operator authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _tokens_match(presented: str, expected: str) -> bool:
    """Timing-safe UTF-8 string comparison."""
    return hmac.compare_digest(
        presented.encode("utf-8"), expected.encode("utf-8")
    )


class SessionStore:
    """In-memory, per-process session store.

    Each session has an absolute ``max_age_seconds`` lifetime and a sliding
    ``idle_seconds`` expiry. Sessions also carry a separate random key that must
    be presented for any unsafe (non-read) request.
    """

    def __init__(
        self,
        idle_seconds: float,
        max_age_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.idle_seconds = idle_seconds
        self.max_age_seconds = max_age_seconds
        self.clock = clock
        self._sessions: dict[str, dict[str, float | str]] = {}
        self._lock = threading.Lock()

    def create(self) -> tuple[str, str]:
        """Create a session and return (session_id, session_key).

        The session key is delivered exactly once to the client at login.
        """
        now = self.clock()
        session_id = secrets.token_urlsafe(32)
        session_key = secrets.token_urlsafe(32)
        with self._lock:
            self._prune_expired(now)
            self._sessions[session_id] = {
                "created_at": now,
                "last_seen": now,
                "key": session_key,
            }
        return session_id, session_key

    def validate(self, session_id: str | None) -> bool:
        """Sliding-window validation; rejects absolute-lifetime expiry too."""
        if session_id is None:
            return False
        now = self.clock()
        with self._lock:
            record = self._sessions.get(session_id)
            if record is None:
                return False
            if now - record["last_seen"] > self.idle_seconds:  # type: ignore[operator]
                del self._sessions[session_id]
                return False
            if now - record["created_at"] > self.max_age_seconds:  # type: ignore[operator]
                del self._sessions[session_id]
                return False
            record["last_seen"] = now  # type: ignore[index]
            return True

    def key_matches(self, session_id: str | None, presented_key: str | None) -> bool:
        """True only when the session is valid and the key matches exactly."""
        if presented_key is None or not self.validate(session_id):
            return False
        with self._lock:
            record = self._sessions.get(session_id)
            if record is None:
                return False
            expected = record["key"]
            assert isinstance(expected, str)
            return hmac.compare_digest(
                presented_key.encode("utf-8"),
                expected.encode("utf-8"),
            )

    def revoke(self, session_id: str | None) -> None:
        if session_id is None:
            return
        with self._lock:
            self._sessions.pop(session_id, None)

    def _prune_expired(self, now: float) -> None:
        expired = [
            sid
            for sid, record in self._sessions.items()
            if now - record["last_seen"] > self.idle_seconds  # type: ignore[operator]
            or now - record["created_at"] > self.max_age_seconds  # type: ignore[operator]
        ]
        for sid in expired:
            del self._sessions[sid]


class LoginRateLimiter:
    """Per-key brute-force failure limiter with bounded memory."""

    def __init__(
        self,
        max_failures: int,
        window_s: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_failures = max_failures
        self.window_s = window_s
        self.clock = clock
        self._failures: OrderedDict[str, list[float]] = OrderedDict()

    def record_failure(self, key: str) -> None:
        now = self.clock()
        if key not in self._failures:
            if len(self._failures) >= _MAX_RATE_LIMIT_KEYS:
                self._failures.popitem(last=False)
            self._failures[key] = []
        else:
            self._failures.move_to_end(key)

        cutoff = now - self.window_s
        self._failures[key] = [t for t in self._failures[key] if t >= cutoff]
        self._failures[key].append(now)

    def is_blocked(self, key: str) -> bool:
        now = self.clock()
        failures = self._failures.get(key)
        if failures is None:
            return False

        cutoff = now - self.window_s
        recent = [t for t in failures if t >= cutoff]
        if not recent:
            del self._failures[key]
            return False

        self._failures[key] = recent
        self._failures.move_to_end(key)
        return len(recent) >= self.max_failures

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)


def require_operator_token(request: Request) -> None:
    """FastAPI dependency: validate Bearer token or session cookie+key.

    A valid Bearer token authenticates any HTTP method. Otherwise a valid
    session cookie is sufficient for safe (read) methods; unsafe methods also
    require the matching ``X-Nexus-Session-Key`` header.
    """
    config: Optional[NexusConfig] = getattr(getattr(request, "app", None), "state", None)
    if config is not None:
        config = getattr(config, "config", None)
    if not isinstance(config, NexusConfig):
        log.warning("nexus auth: missing NexusConfig in app.state")
        raise NexusAuthError()

    expected = config.operator_token
    if not expected:
        # No token configured: every privileged request is rejected.
        log.warning("nexus auth: request rejected because operator_token is not configured")
        raise NexusAuthError()

    auth = request.headers.get("Authorization", "")
    if auth.startswith(_AUTH_HEADER_PREFIX):
        presented = auth[len(_AUTH_HEADER_PREFIX) :]
        if _tokens_match(presented, expected):
            return
        log.warning("nexus auth: invalid operator token presented")

    sessions = getattr(request.app.state, "sessions", None)
    if sessions is not None:
        session_id = request.cookies.get(SESSION_COOKIE)
        if sessions.validate(session_id):
            if request.method in _SAFE_METHODS:
                return
            presented_key = request.headers.get(SESSION_KEY_HEADER)
            if sessions.key_matches(session_id, presented_key):
                return

    raise NexusAuthError()


def build_auth_router(config: NexusConfig) -> APIRouter:
    """Routes for operator login, logout, and the login form."""
    router = APIRouter()

    async def _read_limited_body(request: Request) -> bytes | None:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                length = int(content_length)
            except ValueError:
                return None
            if length > _MAX_LOGIN_BODY_BYTES:
                return None

        chunks: list[bytes] = []
        total = 0
        async for chunk in request.stream():
            chunks.append(chunk)
            total += len(chunk)
            if total > _MAX_LOGIN_BODY_BYTES:
                return None
        return b"".join(chunks)

    def _set_no_store(response):
        response.headers["Cache-Control"] = "no-store"
        return response

    @router.get("/login", response_class=HTMLResponse, response_model=None)
    async def login_page(request: Request) -> HTMLResponse:
        error = request.query_params.get("error")
        message = ""
        if error == "1":
            message = "Invalid token."
        elif error == "locked":
            message = "Too many attempts; wait and try again."
        elif error == "nojs":
            message = "JavaScript is required to sign in to the control surface."

        html = (
            "<!DOCTYPE html>"
            "<html>"
            "<head><title>Nexus Login</title></head>"
            "<body>"
            f'<form id="nexus-login-form" method="post" action="/auth/login">'
            "<p>Enter the operator token from KAINE_NEXUS_TOKEN or config/secrets.toml.</p>"
            f'<input id="nexus-login-token" type="password" name="token" autocomplete="current-password" />'
            '<button type="submit">Log in</button>'
            "</form>"
            f'<p id="nexus-login-error">{message}</p>'
            '<script src="/static/nexus_auth.js"></script>'
            "</body>"
            "</html>"
        )
        response = _set_no_store(HTMLResponse(html))
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "frame-ancestors 'none'; form-action 'self'"
        )
        return response

    @router.post("/auth/login", response_model=None)
    async def login(request: Request) -> RedirectResponse | JSONResponse:
        body = await _read_limited_body(request)
        if body is None:
            return _set_no_store(
                JSONResponse(
                    {"detail": "request too large"},
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                )
            )

        try:
            parsed = urllib.parse.parse_qs(body.decode("utf-8"))
        except UnicodeDecodeError:
            parsed = {}

        token = parsed.get("token", [""])[0]
        key = getattr(request.client, "host", None) or "unknown"
        accepts_json = "application/json" in request.headers.get("Accept", "").lower()

        if not config.operator_token:
            return _set_no_store(
                JSONResponse(
                    {"detail": "operator token not configured"},
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            )

        limiter: LoginRateLimiter = request.app.state.login_limiter
        sessions: SessionStore = request.app.state.sessions

        # Compare the token first; a correct token is never refused by the limiter.
        if _tokens_match(token, config.operator_token):
            limiter.reset(key)
            if not accepts_json:
                # Plain form post with no JS cannot receive the one-time key,
                # so do not create a session at all.
                return _set_no_store(
                    RedirectResponse(
                        "/login?error=nojs",
                        status_code=status.HTTP_303_SEE_OTHER,
                    )
                )
            session_id, session_key = sessions.create()
            response = JSONResponse(
                {"session_key": session_key, "redirect": "/"},
                status_code=status.HTTP_200_OK,
            )
            response.set_cookie(
                SESSION_COOKIE,
                session_id,
                httponly=True,
                samesite="strict",
                path="/",
                secure=request.url.scheme == "https",
                max_age=int(config.session_idle_minutes * 60),
            )
            return _set_no_store(response)

        # Wrong token: apply rate limiting.
        if limiter.is_blocked(key):
            if accepts_json:
                return _set_no_store(
                    JSONResponse(
                        {"detail": "Too many attempts; wait and try again."},
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    )
                )
            return _set_no_store(
                RedirectResponse(
                    "/login?error=locked",
                    status_code=status.HTTP_303_SEE_OTHER,
                )
            )

        limiter.record_failure(key)

        if accepts_json:
            return _set_no_store(
                JSONResponse(
                    {"detail": "invalid operator token"},
                    status_code=status.HTTP_401_UNAUTHORIZED,
                )
            )
        return _set_no_store(
            RedirectResponse(
                "/login?error=1",
                status_code=status.HTTP_303_SEE_OTHER,
            )
        )

    @router.post(
        "/auth/logout",
        dependencies=[Depends(require_operator_token)],
        response_model=None,
    )
    async def logout(request: Request) -> RedirectResponse:
        sessions: SessionStore = request.app.state.sessions
        session_id = request.cookies.get(SESSION_COOKIE)
        presented_key = request.headers.get(SESSION_KEY_HEADER)
        # Only revoke if the cookie and the matching one-time key are both
        # presented. A stolen cookie alone must not be able to log out.
        if sessions.key_matches(session_id, presented_key):
            sessions.revoke(session_id)

        response = RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
        response.delete_cookie(
            SESSION_COOKIE,
            path="/",
            httponly=True,
            samesite="strict",
        )
        return _set_no_store(response)

    return router


async def auth_error_handler(
    request: Request,
    exc: NexusAuthError,
) -> RedirectResponse | JSONResponse:
    if (
        request.method in ("GET", "HEAD")
        and "text/html" in request.headers.get("Accept", "").lower()
    ):
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=exc.headers,
    )
