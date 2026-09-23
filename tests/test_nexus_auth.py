# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
import time

import httpx
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.responses import HTMLResponse

from kaine.nexus.app import create_app
from kaine.nexus.auth import (
    SESSION_COOKIE,
    SESSION_KEY_HEADER,
    LoginRateLimiter,
    NexusAuthError,
    SessionStore,
    _tokens_match,
    auth_error_handler,
    build_auth_router,
    require_operator_token,
)
from kaine.nexus.config import NexusConfig

TOKEN = "s3cret-operator-token"
HTML_ACCEPT = {"Accept": "text/html"}
JSON_ACCEPT = {"Accept": "application/json"}


def _app(config: NexusConfig) -> FastAPI:
    app = FastAPI()
    app.state.config = config
    app.state.sessions = SessionStore(
        idle_seconds=config.session_idle_minutes * 60,
        max_age_seconds=getattr(config, "session_max_hours", 24) * 3600,
    )
    app.state.login_limiter = LoginRateLimiter(
        max_failures=config.login_max_failures,
        window_s=config.login_failure_window_s,
    )
    app.add_exception_handler(NexusAuthError, auth_error_handler)
    app.include_router(build_auth_router(config))

    @app.post("/mutate")
    async def mutate(_=Depends(require_operator_token)):
        return {"ok": True}

    @app.get("/read")
    async def read(_=Depends(require_operator_token)):
        return {"ok": True}

    return app


def _wired_app(config: NexusConfig, clock=None) -> FastAPI:
    app = FastAPI()
    app.state.config = config
    app.state.sessions = SessionStore(
        idle_seconds=config.session_idle_minutes * 60,
        max_age_seconds=getattr(config, "session_max_hours", 24) * 3600,
        clock=clock or time.monotonic,
    )
    app.state.login_limiter = LoginRateLimiter(
        max_failures=config.login_max_failures,
        window_s=config.login_failure_window_s,
        clock=clock or time.monotonic,
    )
    app.add_exception_handler(NexusAuthError, auth_error_handler)
    app.include_router(build_auth_router(config))

    @app.get("/api/gated")
    async def gated_json(_=Depends(require_operator_token)):
        return {"ok": True}

    @app.get("/html/gated")
    async def gated_html(_=Depends(require_operator_token)):
        return HTMLResponse("<p>secret</p>")

    @app.post("/api/gated")
    async def gated_post(_=Depends(require_operator_token)):
        return {"ok": True}

    return app


def test_missing_config_rejects():
    app = FastAPI()

    @app.post("/mutate")
    async def mutate(_=Depends(require_operator_token)):
        return {"ok": True}

    client = TestClient(app)
    r = client.post("/mutate", headers={"Authorization": "Bearer x"})
    assert r.status_code == 401
    assert r.json()["detail"] == "operator authentication required"


def test_no_token_configured_rejects():
    config = NexusConfig(operator_token="")
    client = TestClient(_app(config))
    r = client.post("/mutate", headers={"Authorization": "Bearer x"})
    assert r.status_code == 401


def test_missing_header_rejects():
    config = NexusConfig(operator_token="s3cret")
    client = TestClient(_app(config))
    r = client.post("/mutate")
    assert r.status_code == 401
    assert "WWW-Authenticate" in r.headers
    assert r.headers["WWW-Authenticate"] == "Bearer"


def test_wrong_token_rejects():
    config = NexusConfig(operator_token="s3cret")
    client = TestClient(_app(config))
    r = client.post("/mutate", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_correct_token_allows():
    config = NexusConfig(operator_token="s3cret")
    client = TestClient(_app(config))
    r = client.post("/mutate", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_tokens_match_equal_different_and_different_length():
    assert _tokens_match("abc", "abc") is True
    assert _tokens_match("abc", "abC") is False
    assert _tokens_match("abc", "abcd") is False
    assert _tokens_match("", "") is True
    assert _tokens_match("ü", "ü") is True


def test_auth_error_has_bearer_www_authenticate():
    exc = NexusAuthError()
    assert exc.status_code == 401
    assert exc.headers == {"WWW-Authenticate": "Bearer"}


def test_session_store_create_validate_revoke_expiry_and_unknown():
    now = [0.0]

    def clock():
        return now[0]

    store = SessionStore(idle_seconds=60.0, max_age_seconds=300.0, clock=clock)

    sid, skey = store.create()
    assert sid
    assert skey
    assert store.validate(sid) is True

    now[0] += 30.0
    assert store.validate(sid) is True

    now[0] += 59.0
    assert store.validate(sid) is True

    now[0] += 61.0
    assert store.validate(sid) is False

    assert store.validate("unknown-session") is False
    assert store.validate(None) is False

    sid2, skey2 = store.create()
    store.revoke(sid2)
    assert store.validate(sid2) is False

    # key_matches requires a valid session and a key.
    sid3, skey3 = store.create()
    assert store.key_matches(sid3, skey3) is True
    assert store.key_matches(sid3, "wrong") is False
    assert store.key_matches(sid3, None) is False
    store.revoke(sid3)
    assert store.key_matches(sid3, skey3) is False


def test_session_key_returned_once_and_absent_from_gets():
    config = NexusConfig(operator_token=TOKEN)
    app = _wired_app(config)
    client = TestClient(app, base_url="http://127.0.0.1:8088")

    r = client.post(
        "/auth/login",
        data={"token": TOKEN},
        headers=JSON_ACCEPT,
        follow_redirects=False,
    )
    assert r.status_code == 200
    body = r.json()
    assert "session_key" in body
    key = body["session_key"]
    assert len(key) > 0

    # The key must never appear on any read surface.
    assert key not in client.get("/login", follow_redirects=False).text
    assert key not in client.get("/api/gated", follow_redirects=False).text
    assert key not in client.get("/html/gated", follow_redirects=False).text


def test_login_rate_limiter_blocks_resets_and_unblocks():
    now = [0.0]

    def clock():
        return now[0]

    limiter = LoginRateLimiter(max_failures=3, window_s=100.0, clock=clock)

    limiter.record_failure("k1")
    limiter.record_failure("k1")
    assert limiter.is_blocked("k1") is False

    limiter.record_failure("k1")
    assert limiter.is_blocked("k1") is True

    now[0] += 101.0
    assert limiter.is_blocked("k1") is False

    limiter.record_failure("k1")
    limiter.record_failure("k1")
    assert limiter.is_blocked("k1") is False

    limiter.record_failure("k1")
    assert limiter.is_blocked("k1") is True

    limiter.reset("k1")
    assert limiter.is_blocked("k1") is False


def test_login_rate_limiter_has_bounded_keys():
    limiter = LoginRateLimiter(max_failures=10, window_s=60.0, clock=time.monotonic)
    for i in range(1026):
        limiter.record_failure(f"key{i}")

    assert len(limiter._failures) == 1024
    assert "key0" not in limiter._failures
    assert "key1" not in limiter._failures
    assert "key1025" in limiter._failures


def test_login_success_sets_cookie_and_cookie_authenticates():
    config = NexusConfig(operator_token=TOKEN, session_idle_minutes=30)
    app = _wired_app(config)
    client = TestClient(app, base_url="http://127.0.0.1:8088")

    r = client.post(
        "/auth/login",
        data={"token": TOKEN},
        headers=JSON_ACCEPT,
        follow_redirects=False,
    )
    assert r.status_code == 200
    body = r.json()
    assert "session_key" in body
    assert body["redirect"] == "/"
    assert SESSION_COOKIE in r.cookies

    set_cookie = r.headers["set-cookie"]
    assert "HttpOnly" in set_cookie
    assert "SameSite=strict" in set_cookie
    # max-age tracks the absolute server-side session cap (default 24h).
    assert "Max-Age=86400" in set_cookie
    assert TOKEN not in r.cookies[SESSION_COOKIE]
    assert TOKEN not in r.text

    # Cookie-only GET on a gated JSON route succeeds.
    gated = client.get("/api/gated")
    assert gated.status_code == 200
    assert gated.json() == {"ok": True}

    # Cookie-only POST on a gated route fails.
    post_no_key = client.post("/api/gated", follow_redirects=False)
    assert post_no_key.status_code == 401

    # Cookie + correct key POST succeeds.
    post_with_key = client.post(
        "/api/gated",
        headers={SESSION_KEY_HEADER: body["session_key"]},
        follow_redirects=False,
    )
    assert post_with_key.status_code == 200
    assert post_with_key.json() == {"ok": True}

    # Cookie + wrong key POST fails.
    post_wrong_key = client.post(
        "/api/gated",
        headers={SESSION_KEY_HEADER: "wrong-key"},
        follow_redirects=False,
    )
    assert post_wrong_key.status_code == 401


def test_bearer_post_without_cookie_allows():
    config = NexusConfig(operator_token=TOKEN)
    app = _wired_app(config)
    client = TestClient(app, base_url="http://127.0.0.1:8088")

    r = client.post(
        "/api/gated",
        headers={"Authorization": f"Bearer {TOKEN}"},
        follow_redirects=False,
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_login_wrong_token_no_cookie_json_401_browser_redirect():
    config = NexusConfig(operator_token=TOKEN)
    app = _wired_app(config)
    client = TestClient(app, base_url="http://127.0.0.1:8088")

    r_json = client.post(
        "/auth/login",
        data={"token": "wrong"},
        headers=JSON_ACCEPT,
        follow_redirects=False,
    )
    assert r_json.status_code == 401
    assert "set-cookie" not in {k.lower() for k in r_json.headers.keys()}

    r_html = client.post(
        "/auth/login",
        data={"token": "wrong"},
        headers=HTML_ACCEPT,
        follow_redirects=False,
    )
    assert r_html.status_code == 303
    assert r_html.headers["Location"] == "/login?error=1"
    assert "set-cookie" not in {k.lower() for k in r_html.headers.keys()}


def test_blocked_wrong_attempts_get_429():
    config = NexusConfig(operator_token=TOKEN, login_max_failures=2)
    app = _wired_app(config)
    client = TestClient(app, base_url="http://127.0.0.1:8088")

    assert client.post(
        "/auth/login", data={"token": "bad"}, headers=JSON_ACCEPT
    ).status_code == 401
    assert client.post(
        "/auth/login", data={"token": "bad"}, headers=JSON_ACCEPT
    ).status_code == 401

    blocked = client.post(
        "/auth/login", data={"token": "bad"}, headers=JSON_ACCEPT
    )
    assert blocked.status_code == 429
    assert blocked.json()["detail"] == "Too many attempts; wait and try again."


def test_correct_token_logs_in_after_limiter_exhausted(monkeypatch):
    config = NexusConfig(
        operator_token=TOKEN,
        login_max_failures=2,
        login_block_delay_s=0.5,
    )
    app = _wired_app(config)
    client = TestClient(app, base_url="http://127.0.0.1:8088")

    slept: list[float] = []

    async def fake_sleep(delay: float) -> None:
        slept.append(delay)

    monkeypatch.setattr("kaine.nexus.auth._sleep", fake_sleep)

    assert (
        client.post(
            "/auth/login", data={"token": "bad"}, headers=JSON_ACCEPT
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/auth/login", data={"token": "bad"}, headers=JSON_ACCEPT
        ).status_code
        == 401
    )
    assert slept == []

    # Correct token submitted while the client is blocked still signs in,
    # after waiting its turn.
    r = client.post(
        "/auth/login",
        data={"token": TOKEN},
        headers=JSON_ACCEPT,
        follow_redirects=False,
    )
    assert r.status_code == 200
    assert "session_key" in r.json()
    assert slept == [0.5]


def test_login_rate_limit_locks_out_wrong_attempts(monkeypatch):
    now = [0.0]

    def clock():
        return now[0]

    config = NexusConfig(
        operator_token=TOKEN,
        login_max_failures=2,
        login_failure_window_s=60,
        login_block_delay_s=0.5,
    )
    app = _wired_app(config, clock=clock)
    client = TestClient(app, base_url="http://127.0.0.1:8088")

    slept: list[float] = []

    async def fake_sleep(delay: float) -> None:
        slept.append(delay)

    monkeypatch.setattr("kaine.nexus.auth._sleep", fake_sleep)

    assert (
        client.post(
            "/auth/login", data={"token": "bad"}, headers=JSON_ACCEPT
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/auth/login", data={"token": "bad"}, headers=JSON_ACCEPT
        ).status_code
        == 401
    )
    assert slept == []

    blocked = client.post(
        "/auth/login", data={"token": "bad"}, headers=JSON_ACCEPT
    )
    assert blocked.status_code == 429
    assert slept == [0.5]

    now[0] += 61.0
    allowed = client.post(
        "/auth/login",
        data={"token": TOKEN},
        headers=JSON_ACCEPT,
        follow_redirects=False,
    )
    assert allowed.status_code == 200
    assert "session_key" in allowed.json()
    assert slept == [0.5]


def test_plain_form_post_redirects_nojs_without_session():
    config = NexusConfig(operator_token=TOKEN)
    app = _wired_app(config)
    client = TestClient(app, base_url="http://127.0.0.1:8088")

    r = client.post(
        "/auth/login",
        data={"token": TOKEN},
        headers=HTML_ACCEPT,
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["Location"] == "/login?error=nojs"
    assert "set-cookie" not in {k.lower() for k in r.headers.keys()}

    # No session was created, so the gated route still rejects.
    assert client.get("/api/gated", follow_redirects=False).status_code == 401


def test_session_absolute_max_age_expiry_even_when_active():
    now = [0.0]

    def clock():
        return now[0]

    config = NexusConfig(operator_token=TOKEN, session_idle_minutes=60)
    app = _wired_app(config, clock=clock)
    client = TestClient(app, base_url="http://127.0.0.1:8088")

    r = client.post(
        "/auth/login",
        data={"token": TOKEN},
        headers=JSON_ACCEPT,
        follow_redirects=False,
    )
    assert r.status_code == 200

    # Active within the idle window.
    now[0] += 60 * 60  # 1 hour
    assert client.get("/api/gated").status_code == 200

    # Beyond the default absolute max age of 24 hours.
    now[0] += 23 * 60 * 60 + 1
    assert client.get("/api/gated", follow_redirects=False).status_code == 401


def test_logout_with_cookie_only_does_not_revoke():
    config = NexusConfig(operator_token=TOKEN)
    app = _wired_app(config)
    client = TestClient(app, base_url="http://127.0.0.1:8088")

    r = client.post(
        "/auth/login",
        data={"token": TOKEN},
        headers=JSON_ACCEPT,
        follow_redirects=False,
    )
    assert r.status_code == 200

    # Cookie-only GET works.
    assert client.get("/api/gated").status_code == 200

    # Logout is a state change: cookie alone is rejected.
    logout = client.post("/auth/logout", follow_redirects=False)
    assert logout.status_code == 401

    # Session is still valid for GET.
    assert client.get("/api/gated").status_code == 200


def test_logout_with_cookie_and_key_revokes():
    config = NexusConfig(operator_token=TOKEN)
    app = _wired_app(config)
    client = TestClient(app, base_url="http://127.0.0.1:8088")

    r = client.post(
        "/auth/login",
        data={"token": TOKEN},
        headers=JSON_ACCEPT,
        follow_redirects=False,
    )
    key = r.json()["session_key"]

    assert client.get("/api/gated").status_code == 200

    logout = client.post(
        "/auth/logout",
        headers={SESSION_KEY_HEADER: key},
        follow_redirects=False,
    )
    assert logout.status_code == 303
    assert logout.headers["Location"] == "/login"

    assert client.get("/api/gated", follow_redirects=False).status_code == 401


def test_unauthenticated_get_html_redirects_json_returns_401():
    config = NexusConfig(operator_token=TOKEN)
    app = _wired_app(config)
    client = TestClient(app, base_url="http://127.0.0.1:8088")

    r_html = client.get("/api/gated", headers=HTML_ACCEPT, follow_redirects=False)
    assert r_html.status_code == 303
    assert r_html.headers["Location"] == "/login"

    r_html_page = client.get(
        "/html/gated",
        headers=HTML_ACCEPT,
        follow_redirects=False,
    )
    assert r_html_page.status_code == 303

    r_json = client.get("/api/gated", follow_redirects=False)
    assert r_json.status_code == 401
    assert r_json.json()["detail"] == "operator authentication required"


def test_bearer_still_works_empty_token_rejects_login():
    # Bearer continues to work when a token is configured.
    config = NexusConfig(operator_token=TOKEN)
    app = _wired_app(config)
    client = TestClient(app, base_url="http://127.0.0.1:8088")

    r = client.get(
        "/api/gated",
        headers={"Authorization": f"Bearer {TOKEN}"},
        follow_redirects=False,
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True}

    # With an empty configured token even login is unavailable.
    empty_config = NexusConfig(operator_token="")
    empty_app = _wired_app(empty_config)
    empty_client = TestClient(empty_app, base_url="http://127.0.0.1:8088")

    r_login = empty_client.post(
        "/auth/login",
        data={"token": TOKEN},
        headers=JSON_ACCEPT,
        follow_redirects=False,
    )
    assert r_login.status_code == 503
    assert r_login.json()["detail"] == "operator token not configured"

    # An existing/session cookie cannot bypass the missing-token policy.
    r_gated = empty_client.get(
        "/api/gated",
        headers={"Cookie": f"{SESSION_COOKIE}=fake-session-id"},
        follow_redirects=False,
    )
    assert r_gated.status_code == 401


def test_login_page_has_csp_and_external_script_only():
    config = NexusConfig(operator_token=TOKEN)
    app = _wired_app(config)
    client = TestClient(app, base_url="http://127.0.0.1:8088")

    r = client.get("/login")
    assert r.status_code == 200
    assert r.headers.get("Cache-Control") == "no-store"
    assert "text/html" in r.headers.get("content-type", "")

    csp = r.headers.get("Content-Security-Policy")
    assert csp is not None
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "style-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "form-action 'self'" in csp

    body = r.text
    assert 'id="nexus-login-form"' in body
    assert 'id="nexus-login-token"' in body
    assert 'id="nexus-login-error"' in body
    assert 'action="/auth/login"' in body
    assert 'method="post"' in body
    assert 'type="password"' in body
    assert 'name="token"' in body
    assert '<script src="/static/nexus_auth.js"></script>' in body
    # No inline <script> tags.
    assert "<script>" not in body.lower()

    r_err = client.get("/login?error=1")
    assert "Invalid token." in r_err.text

    r_locked = client.get("/login?error=locked")
    assert "Too many attempts; wait and try again." in r_locked.text

    r_nojs = client.get("/login?error=nojs")
    assert "JavaScript is required to sign in to the control surface." in r_nojs.text


def test_login_rejects_oversized_request_via_content_length():
    config = NexusConfig(operator_token=TOKEN)
    app = _wired_app(config)
    client = TestClient(app, base_url="http://127.0.0.1:8088")

    r_invalid = client.post(
        "/auth/login",
        content=b"token=x",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Content-Length": "not-a-number",
        },
        follow_redirects=False,
    )
    assert r_invalid.status_code == 413
    assert r_invalid.json()["detail"] == "request too large"
    assert r_invalid.headers.get("Cache-Control") == "no-store"

    r_large = client.post(
        "/auth/login",
        content=b"token=x",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Content-Length": "8192",
        },
        follow_redirects=False,
    )
    assert r_large.status_code == 413
    assert r_large.json()["detail"] == "request too large"
    assert r_large.headers.get("Cache-Control") == "no-store"


def test_login_rejects_oversized_request_via_streamed_body():
    config = NexusConfig(operator_token=TOKEN)
    app = _wired_app(config)
    client = TestClient(app, base_url="http://127.0.0.1:8088")

    # No Content-Length; the body is streamed and exceeds the 4096-byte limit.
    body = b"token=" + b"x" * 4091  # 4097 bytes total
    r = client.post(
        "/auth/login",
        content=iter([body]),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )
    assert r.status_code == 413
    assert r.json()["detail"] == "request too large"
    assert r.headers.get("Cache-Control") == "no-store"


def test_login_page_and_login_logout_responses_send_no_store_cache_control():
    config = NexusConfig(operator_token=TOKEN)
    app = _wired_app(config)
    client = TestClient(app, base_url="http://127.0.0.1:8088")

    r_page = client.get("/login")
    assert r_page.status_code == 200
    assert r_page.headers.get("Cache-Control") == "no-store"

    r_success = client.post(
        "/auth/login",
        data={"token": TOKEN},
        headers=JSON_ACCEPT,
        follow_redirects=False,
    )
    assert r_success.status_code == 200
    assert r_success.headers.get("Cache-Control") == "no-store"

    r_error = client.post(
        "/auth/login",
        data={"token": "wrong"},
        headers=HTML_ACCEPT,
        follow_redirects=False,
    )
    assert r_error.status_code == 303
    assert r_error.headers.get("Cache-Control") == "no-store"

    key = r_success.json()["session_key"]
    r_logout = client.post(
        "/auth/logout",
        headers={SESSION_KEY_HEADER: key},
        follow_redirects=False,
    )
    assert r_logout.status_code == 303
    assert r_logout.headers.get("Cache-Control") == "no-store"


def test_create_app_serves_health_json_without_auth():
    """Task 7.9: /diagnostics/health.json is mounted without auth dependencies."""
    class StubBridge:
        async def start(self):
            pass
        async def stop(self):
            pass
        async def publish_synthetic(self, **kwargs):
            pass

    config = NexusConfig(
        operator_token="",
        conversation_enabled=True,
        diagnostics_enabled=True,
    )
    app = create_app(
        config=config,
        bridge=StubBridge(),  # type: ignore[arg-type]
        history_loader=lambda n: [],
        metrics_snapshot=lambda: {},
    )
    with TestClient(app, base_url="http://127.0.0.1:8088") as client:
        r = client.get("/diagnostics/health.json")
        assert r.status_code == 200
        assert "checked_at" in r.json()


def test_blocked_login_attempts_sleep_before_token_check(monkeypatch):
    """M1: blocked clients are slowed before the token is checked."""
    config = NexusConfig(
        operator_token=TOKEN,
        login_max_failures=2,
        login_block_delay_s=1.25,
    )
    app = _wired_app(config)
    client = TestClient(app, base_url="http://127.0.0.1:8088")

    slept: list[float] = []

    async def fake_sleep(delay: float) -> None:
        slept.append(delay)

    monkeypatch.setattr("kaine.nexus.auth._sleep", fake_sleep)

    # First two wrong attempts are not blocked at request start: no sleep.
    assert (
        client.post(
            "/auth/login", data={"token": "bad1"}, headers=JSON_ACCEPT
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/auth/login", data={"token": "bad2"}, headers=JSON_ACCEPT
        ).status_code
        == 401
    )
    assert slept == []

    # Third attempt starts blocked; it sleeps, then the wrong token yields 429.
    blocked_wrong = client.post(
        "/auth/login", data={"token": "bad3"}, headers=JSON_ACCEPT
    )
    assert blocked_wrong.status_code == 429
    assert blocked_wrong.json()["detail"] == "Too many attempts; wait and try again."
    assert slept == [1.25]

    # Blocked client with the correct token sleeps, then logs in successfully.
    blocked_correct = client.post(
        "/auth/login",
        data={"token": TOKEN},
        headers=JSON_ACCEPT,
        follow_redirects=False,
    )
    assert blocked_correct.status_code == 200
    assert "session_key" in blocked_correct.json()
    assert slept == [1.25, 1.25]

    # A successful login resets the limiter; further requests do not sleep.
    slept.clear()
    after_reset = client.post(
        "/auth/login",
        data={"token": TOKEN},
        headers=JSON_ACCEPT,
        follow_redirects=False,
    )
    assert after_reset.status_code == 200
    assert slept == []


def test_concurrent_blocked_login_attempts_serialize_delay(monkeypatch):
    """Blocked login attempts for the same client are serialized, not run in parallel."""
    config = NexusConfig(
        operator_token=TOKEN,
        login_max_failures=1,
        login_block_delay_s=0.1,
    )
    app = _wired_app(config)

    max_concurrent = [0]
    current = [0]
    sleeps: list[float] = []

    async def instrumented_sleep(delay: float) -> None:
        sleeps.append(delay)
        current[0] += 1
        max_concurrent[0] = max(max_concurrent[0], current[0])
        await asyncio.sleep(0.01)
        current[0] -= 1

    monkeypatch.setattr("kaine.nexus.auth._sleep", instrumented_sleep)

    async def _run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            # Seed one failure so all subsequent attempts start blocked.
            seed = await client.post(
                "/auth/login", data={"token": "bad"}, headers=JSON_ACCEPT
            )
            assert seed.status_code == 401

            async def one_attempt():
                return await client.post(
                    "/auth/login", data={"token": "bad"}, headers=JSON_ACCEPT
                )

            return await asyncio.gather(*[
                asyncio.create_task(one_attempt()) for _ in range(5)
            ])

    responses = asyncio.run(_run())

    for r in responses:
        assert r.status_code == 429
        assert r.json()["detail"] == "Too many attempts; wait and try again."

    assert len(sleeps) == 5
    assert max_concurrent[0] == 1


def test_create_app_responses_carry_frame_protection_headers():
    """M2: every response gets X-Frame-Options and a CSP frame-ancestors directive."""
    class StubBridge:
        async def start(self):
            pass
        async def stop(self):
            pass
        async def publish_synthetic(self, **kwargs):
            pass

    config = NexusConfig(
        operator_token=TOKEN,
        conversation_enabled=True,
        diagnostics_enabled=True,
    )
    app = create_app(
        config=config,
        bridge=StubBridge(),  # type: ignore[arg-type]
        history_loader=lambda n: [],
        metrics_snapshot=lambda: {},
    )
    with TestClient(app, base_url="http://127.0.0.1:8088") as client:
        # Login page keeps its own full CSP; middleware adds X-Frame-Options only.
        r_login = client.get("/login")
        assert r_login.status_code == 200
        assert r_login.headers.get("X-Frame-Options") == "DENY"
        csp_login = r_login.headers.get("Content-Security-Policy")
        assert csp_login is not None
        assert "frame-ancestors 'none'" in csp_login
        assert csp_login.count("frame-ancestors") == 1

        # Health JSON gets both headers.
        r_health = client.get("/diagnostics/health.json")
        assert r_health.status_code == 200
        assert r_health.headers.get("X-Frame-Options") == "DENY"
        csp_health = r_health.headers.get("Content-Security-Policy")
        assert csp_health == "frame-ancestors 'none'"

        # A generic JSON failure route also gets both headers.
        r_json = client.post(
            "/auth/login", data={"token": "wrong"}, headers=JSON_ACCEPT
        )
        assert r_json.status_code == 401
        assert r_json.headers.get("X-Frame-Options") == "DENY"
        csp_json = r_json.headers.get("Content-Security-Policy")
        assert "frame-ancestors 'none'" in csp_json
        assert csp_json.count("frame-ancestors") == 1


def test_login_cookie_max_age_uses_session_max_hours():
    """L1: cookie lifetime follows the absolute server-side session cap."""
    config = NexusConfig(operator_token=TOKEN, session_max_hours=2)
    app = _wired_app(config)
    client = TestClient(app, base_url="http://127.0.0.1:8088")

    r = client.post(
        "/auth/login",
        data={"token": TOKEN},
        headers=JSON_ACCEPT,
        follow_redirects=False,
    )
    assert r.status_code == 200
    set_cookie = r.headers["set-cookie"]
    assert "Max-Age=7200" in set_cookie


def test_conversation_read_gate_evaluation_requires_bearer():
    """L3: privileged read surfaces require Bearer authentication."""
    class StubBridge:
        async def start(self):
            pass
        async def stop(self):
            pass
        async def publish_synthetic(self, **kwargs):
            pass

    config = NexusConfig(
        operator_token=TOKEN,
        conversation_enabled=True,
        diagnostics_enabled=True,
    )
    app = create_app(
        config=config,
        bridge=StubBridge(),  # type: ignore[arg-type]
        history_loader=lambda n: [],
        metrics_snapshot=lambda: {},
    )

    eval_router = APIRouter()

    @eval_router.get(
        "/diagnostics/evaluation/summary.json",
        dependencies=list(app.state.read_dependencies),
    )
    async def eval_summary():
        return {"summary": True}

    app.include_router(eval_router)

    with TestClient(app, base_url="http://127.0.0.1:8088") as client:
        r_unauth = client.get("/diagnostics/evaluation/summary.json")
        assert r_unauth.status_code == 401

        r_auth = client.get(
            "/diagnostics/evaluation/summary.json",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert r_auth.status_code == 200
        assert r_auth.json() == {"summary": True}


def test_config_repr_hides_operator_token():
    """L5: repr must not leak the configured operator token."""
    config = NexusConfig(operator_token="x" * 40)
    representation = repr(config)
    assert "x" * 40 not in representation
    assert "operator_token" not in representation
