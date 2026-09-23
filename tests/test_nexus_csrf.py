# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import FastAPI
from starlette.testclient import TestClient

from kaine.nexus.config import NexusConfig
from kaine.nexus.csrf import (
    NexusCSRFMiddleware,
    _host_allowed,
    _is_loopback,
    _origin_matches,
    _parse_host,
)


def _app(config: NexusConfig) -> FastAPI:
    app = FastAPI()
    app.add_middleware(NexusCSRFMiddleware, config=config)

    @app.get("/read")
    async def read():
        return {"ok": True}

    @app.post("/mutate")
    async def mutate():
        return {"ok": True}

    return app


def test_get_with_foreign_host_is_rejected():
    # Updated from old GET-bypass behaviour: Host validation now applies to
    # every request to block DNS-rebinding reads of diagnostics surfaces.
    config = NexusConfig(host="127.0.0.1", allowed_origins=(), host_allowlist=())
    client = TestClient(_app(config))
    r = client.get("/read", headers={"Host": "evil.com"})
    assert r.status_code == 403
    assert r.json()["detail"] == "host not allowed"


def test_get_with_allowed_ipv4_host():
    config = NexusConfig(host="127.0.0.1")
    client = TestClient(_app(config))
    r = client.get("/read", headers={"Host": "127.0.0.1:8088"})
    assert r.status_code == 200


def test_get_with_bracketed_ipv6_host():
    config = NexusConfig(host_allowlist=("::1",))
    client = TestClient(_app(config))
    r = client.get("/read", headers={"Host": "[::1]:8088"})
    assert r.status_code == 200


def test_get_with_malformed_ipv6_host():
    config = NexusConfig(host_allowlist=("::1",))
    client = TestClient(_app(config))
    r = client.get("/read", headers={"Host": "[::1"})
    assert r.status_code == 403
    assert r.json()["detail"] == "host not allowed"


def test_post_with_allowed_origin_succeeds():
    config = NexusConfig(
        host="127.0.0.1",
        allowed_origins=("http://localhost:8088",),
        host_allowlist=("127.0.0.1",),
    )
    client = TestClient(_app(config), base_url="http://127.0.0.1:8088")
    r = client.post("/mutate", headers={"Origin": "http://localhost:8088"})
    assert r.status_code == 200


def test_post_with_disallowed_origin_rejected():
    config = NexusConfig(
        host="127.0.0.1",
        allowed_origins=("http://localhost:8088",),
        host_allowlist=("127.0.0.1",),
    )
    client = TestClient(_app(config), base_url="http://127.0.0.1:8088")
    r = client.post("/mutate", headers={"Origin": "http://evil.com"})
    assert r.status_code == 403
    assert r.json()["detail"] == "cross-origin request rejected"


def test_post_with_allowed_host_succeeds():
    config = NexusConfig(
        host="127.0.0.1",
        allowed_origins=(),
        host_allowlist=("localhost",),
    )
    client = TestClient(_app(config))
    r = client.post("/mutate", headers={"Host": "localhost"})
    assert r.status_code == 200


def test_post_with_disallowed_host_rejected():
    config = NexusConfig(
        host="127.0.0.1",
        allowed_origins=(),
        host_allowlist=("localhost",),
    )
    client = TestClient(_app(config))
    r = client.post("/mutate", headers={"Host": "evil.com"})
    assert r.status_code == 403
    assert r.json()["detail"] == "host not allowed"


def test_post_with_allowed_host_and_matching_origin():
    config = NexusConfig(
        host="127.0.0.1",
        allowed_origins=("http://127.0.0.1:8088",),
        host_allowlist=("127.0.0.1",),
    )
    client = TestClient(_app(config), base_url="http://127.0.0.1:8088")
    r = client.post("/mutate", headers={"Origin": "http://127.0.0.1:8088"})
    assert r.status_code == 200


def test_post_with_foreign_origin_rejected():
    config = NexusConfig(
        host="127.0.0.1",
        allowed_origins=("http://127.0.0.1:8088",),
        host_allowlist=("127.0.0.1",),
    )
    client = TestClient(_app(config), base_url="http://127.0.0.1:8088")
    r = client.post("/mutate", headers={"Origin": "http://evil.com"})
    assert r.status_code == 403
    assert r.json()["detail"] == "cross-origin request rejected"


def test_post_with_bracketed_ipv6_origin_allowed():
    config = NexusConfig(
        host="::1",
        allowed_origins=("http://[::1]:8088",),
        host_allowlist=("::1",),
    )
    client = TestClient(_app(config))
    r = client.post(
        "/mutate",
        headers={"Host": "[::1]:8088", "Origin": "http://[::1]:8088"},
    )
    assert r.status_code == 200


def test_loopback_host_header_not_implicitly_allowed():
    # A loopback Host header is only accepted if it is in host_allowlist.
    # The implicit loopback exception applies only when NO Host header is sent.
    config = NexusConfig(
        host="127.0.0.1",
        allowed_origins=(),
        host_allowlist=(),
    )
    client = TestClient(_app(config))
    r = client.post("/mutate", headers={"Host": "127.0.0.1"})
    assert r.status_code == 403


def test_loopback_bind_allows_missing_host():
    # Direct unit test for the no-Host path (TestClient always injects Host).
    config = NexusConfig(
        host="127.0.0.1",
        allowed_origins=(),
        host_allowlist=(),
    )
    middleware = NexusCSRFMiddleware(FastAPI(), config)
    request = MagicMock()
    request.method = "POST"
    request.headers = {}
    middleware._validate(request)  # should not raise


def test_non_loopback_bind_requires_host_header():
    config = NexusConfig(
        host="192.168.1.5",
        allowed_origins=(),
        host_allowlist=(),
    )
    client = TestClient(_app(config))
    r = client.post("/mutate")
    assert r.status_code == 403


def test_origin_matches_scheme_and_netloc():
    allowed = ("http://localhost:8088", "https://example.com")
    assert _origin_matches("http://localhost:8088", allowed) is True
    assert _origin_matches("https://example.com", allowed) is True
    assert _origin_matches("http://localhost:9999", allowed) is False
    assert _origin_matches("ftp://localhost:8088", allowed) is False


def test_origin_matches_bracketed_ipv6():
    allowed = ("http://[::1]:8088",)
    assert _origin_matches("http://[::1]:8088", allowed) is True
    assert _origin_matches("http://[::1]:9999", allowed) is False


def test_host_allowed_parses_port_and_brackets():
    assert _host_allowed("localhost:8088", ("localhost",)) is True
    assert _host_allowed("evil.com:8088", ("localhost",)) is False
    assert _host_allowed("[::1]:8088", ("::1",)) is True
    assert _host_allowed("[::1]:8088", ("[::1]",)) is True


def test_is_loopback():
    assert _is_loopback("127.0.0.1") is True
    assert _is_loopback("localhost") is True
    assert _is_loopback("::1") is True
    assert _is_loopback("192.168.1.1") is False


def test_parse_host():
    assert _parse_host("localhost") == "localhost"
    assert _parse_host("LOCALHOST:8088") == "localhost"
    assert _parse_host("1.2.3.4:8088") == "1.2.3.4"
    assert _parse_host("[::1]") == "::1"
    assert _parse_host("[::1]:8088") == "::1"
    assert _parse_host("[::1") is None
    assert _parse_host("") is None
    assert _parse_host("localhost:abc") is None
    assert _parse_host("localhost:") is None
    assert _parse_host("::1") is None  # IPv6 must be bracketed in a Host header
